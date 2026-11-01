#!/usr/bin/env python3
"""Non-blocking Codex hook. Only token metadata is retained; no chat text."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat as stat_module
import sys
import tempfile

VERSION = "0.3.1"
TAIL_BYTES = 4 * 1024 * 1024
MAX_STDIN = 8 * 1024 * 1024
EVENTS = {"PostToolUse", "UserPromptSubmit", "PostCompact"}
ACTIONS = {"notify", "prepare", "compact", "new-chat", "compact-and-new-chat"}


def codex_home():
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).resolve()


def read_settings(home):
    p = home / "context-weather.json"
    d = json.loads(p.read_text()) if p.exists() else {}
    threshold = d.get("threshold_percent", 60)
    if type(threshold) is not int or not 1 <= threshold <= 99:
        raise ValueError("invalid_threshold")
    action = d.get("action", "prepare")
    if action not in ACTIONS:
        raise ValueError("invalid_action")
    language = d.get("language", "fr")
    if language not in {"fr", "en"}:
        raise ValueError("invalid_language")
    return {"threshold_percent": threshold, "action": action, "language": language}


def valid_session(value):
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value)


def measure(path, session, home):
    """Bounded adapter for token_count metadata in the native hook transcript.

    The transcript representation is unstable. Unknown/missing data is unknown,
    never zero. The stable app-server event adapter below is also supported.
    """
    if not valid_session(session) or not isinstance(path, str):
        raise ValueError("missing_session_or_path")
    p = Path(path)
    root = (home / "sessions").resolve()
    if not p.is_absolute() or p.is_symlink() or not p.resolve().is_relative_to(root):
        raise ValueError("unapproved_metadata_path")
    fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        with os.fdopen(fd, "rb") as f:
            head = f.readline(65536)
            first = json.loads(head)
            if first.get("type") != "session_meta" or first.get("payload", {}).get("id") != session:
                raise ValueError("session_mismatch")
            stat = os.fstat(f.fileno())
            if not stat_module.S_ISREG(stat.st_mode):
                raise ValueError("not_regular_metadata_file")
            start = max(len(head), stat.st_size - TAIL_BYTES)
            f.seek(start)
            if start > len(head):
                f.readline()  # discard a possibly partial line
            offset = f.tell()
            raw = f.read(TAIL_BYTES)
    except Exception:
        # fd ownership has passed to fdopen.
        raise
    latest = None
    marker = 0
    for line in raw.splitlines(keepends=True):
        end = offset + len(line)
        if not line.endswith(b"\n"):
            break
        if b'"token_count"' in line or b'"compacted"' in line or b'"context_compacted"' in line:
            try:
                d = json.loads(line)
                payload = d.get("payload") or {}
                if d.get("type") == "compacted" or (d.get("type") == "event_msg" and payload.get("type") == "context_compacted"):
                    marker = end
                    latest = None
                elif d.get("type") == "event_msg" and payload.get("type") == "token_count":
                    info = payload.get("info") or {}
                    usage = info.get("last_token_usage") or {}
                    latest = make_sample(usage.get("total_tokens"), info.get("model_context_window"), end, d.get("timestamp"))
            except (ValueError, TypeError, AttributeError):
                # An invalid latest counter cannot be replaced by an older one.
                latest = None
        offset = end
    return {"sample": latest, "marker": marker, "size": stat.st_size,
            "identity": f"{stat.st_dev}:{stat.st_ino}", "adapter": "native-token-count-v1"}


def make_sample(tokens, window, offset=0, timestamp=None):
    if type(tokens) is not int or type(window) is not int or tokens < 0 or window <= 0 or tokens > 2 * window:
        raise ValueError("invalid_token_metadata")
    return {"tokens": tokens, "window": window, "offset": offset,
            "percent": 100 * tokens / window, "timestamp": timestamp}


def app_server_sample(notification):
    """Pure adapter for documented thread/tokenUsage/updated events; no socket."""
    if notification.get("method") != "thread/tokenUsage/updated":
        raise ValueError("unexpected_native_event")
    p = notification["params"]
    usage = p["tokenUsage"]
    return p["threadId"], make_sample(usage["last"]["totalTokens"], usage.get("modelContextWindow"))


def transition(state, measurement, settings, event):
    state = dict(state)
    identity = measurement["identity"]
    marker = measurement["marker"]
    replaced = state.get("identity") is not None and (identity != state["identity"] or measurement["size"] < state.get("size", 0))
    if replaced or marker > max(state.get("marker", 0), state.get("barrier", 0)):
        state["generation"] = state.get("generation", 0) + 1
        state["alerted"] = None
        state["barrier"] = marker
    state.update(identity=identity, size=measurement["size"], marker=marker)
    if event == "PostCompact":
        state["generation"] = state.get("generation", 0) + 1
        state.update(alerted=None, barrier=measurement["size"], status="awaiting_post_compaction_measurement")
        return state, None
    sample = measurement["sample"]
    if sample is None or sample["offset"] <= state.get("barrier", 0):
        state["status"] = "unavailable"
        return state, None
    state.update(status="measured", tokens=sample["tokens"], window=sample["window"],
                 percent=round(sample["percent"], 2), measured_at=sample["timestamp"])
    policy = f"{state.get('generation', 0)}:{settings['threshold_percent']}:{settings['action']}"
    if sample["percent"] < settings["threshold_percent"] or state.get("alerted") == policy:
        return state, None
    state["alerted"] = policy
    percent = math.floor(sample["percent"])
    message = (f"Météo du contexte : {percent} % utilisés (seuil {settings['threshold_percent']} %). "
               "Préparons une reprise au prochain point d’arrêt sûr.")
    context = (f"Alerte native de contexte : dernière mesure {percent} %, seuil configuré {settings['threshold_percent']} %. "
               f"Action configurée : {settings['action']}. Appliquer le skill contexte-reprise-projet au prochain point sûr. "
               "Ne pas interrompre une écriture, rejouer un résultat inconnu, ni dupliquer les automatisations. "
               "Une compaction ou une nouvelle discussion exige une capacité native disponible et une autorisation applicable. "
               "Ne pas annoncer ces actions avant leur vérification.")
    if settings.get("language", "fr") == "en":
        message = (f"Context weather: {percent}% used ({settings['threshold_percent']}% threshold). "
                   "Prepare a handoff at the next safe stopping point.")
        context = (f"Native context alert: latest measurement {percent}%, threshold {settings['threshold_percent']}%. "
                   f"Configured action: {settings['action']}. Use the contexte-reprise-projet skill at the next safe point. "
                   "Respond in English. Do not interrupt writes, replay unknown results or duplicate automations. "
                   "Compaction and new chats require available native capabilities and applicable authorization. "
                   "Do not claim completion before verification.")
    return state, {"systemMessage": message, "hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}


def atomic_json(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".weather-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_hook(payload, home, inspect_only=False):
    event = payload.get("hook_event_name")
    session = payload.get("session_id")
    if event not in EVENTS or not valid_session(session):
        return {}
    settings = read_settings(home)
    if inspect_only:
        measurement = measure(payload.get("transcript_path"), session, home)
        sample = measurement["sample"]
        return {"version": VERSION, "status": "measured" if sample else "unavailable", "settings": settings,
                "adapter": measurement["adapter"], "measurement": sample}
    folder = home / "context-weather-state"
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink():
        raise ValueError("unsafe_state_folder")
    key = hashlib.sha256(session.encode()).hexdigest()
    state_path = folder / f"{key}.json"
    lock_path = folder / f"{key}.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {}
        if state_path.is_symlink():
            raise ValueError("unsafe_state_file")
        measurement = measure(payload.get("transcript_path"), session, home)
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        state, output = transition(state, measurement, settings, event)
        state["version"] = VERSION
        atomic_json(state_path, state)
    if output:
        output["hookSpecificOutput"]["additionalContext"] += (
            f" Chat source : {session}. Afficher aussi une jauge intégrée datée sous la réponse avec le skill visualize, "
            "selon la procédure d’affichage de contexte-reprise-projet ; ne pas ouvrir de panneau latéral par défaut. "
            "Cette jauge est un instantané actualisable sur demande, pas un compteur en direct."
        )
    return output or {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true", help="Read current token metadata; no state writes or alert.")
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(MAX_STDIN + 1)
        if len(raw) > MAX_STDIN:
            raise ValueError("oversized_hook_input")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("invalid_hook_input")
        out = run_hook(payload, codex_home(), inspect_only=args.inspect)
    except Exception:
        # Never expose tool input/output, conversation text, private paths or keys.
        out = {"status": "unavailable"} if args.inspect else {}
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
