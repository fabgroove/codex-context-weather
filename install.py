#!/usr/bin/env python3
"""Install context weather without altering trust or existing hook handlers."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile
import uuid

NAME = "contexte-reprise-projet"
EVENTS = ("PostToolUse", "UserPromptSubmit", "PostCompact")


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None


def save_json(p, d):
    with p.open("x", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")


def merged_hooks(original, command):
    d = json.loads(json.dumps(original))
    hooks = d.setdefault("hooks", {})
    for event in EVENTS:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError("Unknown hook configuration shape")
        found = [h for g in groups for h in g.get("hooks", []) if h.get("command") == command]
        if found:
            if len(found) != 1:
                raise ValueError("Duplicate weather hook")
            if event == "PostCompact":
                found[0].pop("additionalContextLimit", None)
            continue
        handler = {"type": "command", "command": command, "timeout": 3}
        if event != "PostCompact":
            handler["additionalContextLimit"] = 400
        groups.append({"hooks": [handler]})
    return d


def install(home, threshold, action, replace=False, language=None):
    home = home.resolve()
    if not home.is_dir():
        raise ValueError("Codex home must already exist")
    target = home / "skills" / NAME
    hooks = home / "hooks.json"
    config = home / "context-weather.json"
    config_toml = home / "config.toml"
    if any(p.is_symlink() for p in [target, hooks, config, config_toml, home / "skills"]):
        raise ValueError("Symlink target refused")
    if target.exists() and not replace:
        raise ValueError("Existing skill: inspect it, then pass --replace-skill to preserve a backup and update")
    previous = json.loads(hooks.read_text()) if hooks.exists() else {}
    previous_settings = json.loads(config.read_text()) if config.exists() else {}
    language = language or previous_settings.get("language", "fr")
    if language not in {"fr", "en"}:
        raise ValueError("Unsupported language")
    before = {str(p): digest(p) for p in [hooks, config, config_toml]}
    command = "/usr/bin/python3 " + shlex.quote(str(target / "scripts/context_weather.py"))
    candidate = merged_hooks(previous, command)
    source = Path(__file__).resolve().parent / "skills" / NAME
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    backup = home / "context-weather-backups" / stamp
    backup.mkdir(mode=0o700, parents=True)
    for p in [hooks, config]:
        if p.exists():
            shutil.copy2(p, backup / p.name)
            assert digest(p) == digest(backup / p.name)
    if target.exists():
        if any(p.is_symlink() for p in target.rglob("*")):
            raise ValueError("Existing skill contains a symlink")
        shutil.copytree(target, backup / "previous-skill")
    staging = Path(tempfile.mkdtemp(prefix=".context-weather-", dir=home))
    shutil.copytree(source, staging / "skill", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    save_json(staging / "hooks.json", candidate)
    save_json(staging / "context-weather.json", {"version": 1, "threshold_percent": threshold, "action": action, "language": language})
    if any(digest(Path(p)) != h for p, h in before.items()):
        raise ValueError("Concurrent configuration change; nothing replaced")
    # Existing groups remain byte-for-byte equivalent as parsed JSON, at the same indexes.
    for event, groups in previous.get("hooks", {}).items():
        for i, group in enumerate(groups):
            if any(h.get("command") == command for h in group.get("hooks", [])):
                continue
            assert candidate["hooks"][event][i] == group
    target.parent.mkdir(mode=0o700, exist_ok=True)
    if target.exists():
        os.rename(target, backup / "replaced-skill")
    os.rename(staging / "skill", target)
    os.replace(staging / "hooks.json", hooks)
    os.replace(staging / "context-weather.json", config)
    assert digest(config_toml) == before[str(config_toml)], "Trust/config.toml changed unexpectedly"
    assert json.loads(hooks.read_text()) == candidate
    assert json.loads(config.read_text())["threshold_percent"] == threshold
    for p in source.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            assert digest(p) == digest(target / p.relative_to(source))
    receipt = {"status": "installed_pending_native_hook_review", "backup": str(backup),
               "threshold_percent": threshold, "action": action, "language": language, "config_toml_unchanged": True,
               "hooks_sha256": digest(hooks), "skill_sha256": digest(target / "SKILL.md"),
               "files": {str(p.relative_to(target)): digest(p) for p in target.rglob("*") if p.is_file()}}
    save_json(backup / "installation-receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    parser.add_argument("--threshold", type=int, default=60)
    parser.add_argument("--action", choices=["notify", "prepare", "compact", "new-chat", "compact-and-new-chat"], default="prepare")
    parser.add_argument("--replace-skill", action="store_true")
    parser.add_argument("--language", choices=["fr", "en"])
    args = parser.parse_args()
    if not 1 <= args.threshold <= 99:
        parser.error("threshold must be between 1 and 99")
    print(json.dumps(install(args.codex_home, args.threshold, args.action, args.replace_skill, args.language), ensure_ascii=False))
