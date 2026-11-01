#!/usr/bin/env python3
"""Change only the context-weather threshold/action; never hook trust."""
import argparse
import datetime
import json
import os
from pathlib import Path
import uuid
from context_weather import ACTIONS, atomic_json, codex_home, read_settings


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threshold", type=int)
    p.add_argument("--action", choices=sorted(ACTIONS))
    p.add_argument("--language", choices=["fr", "en"])
    a = p.parse_args()
    if a.threshold is not None and not 1 <= a.threshold <= 99:
        p.error("threshold must be between 1 and 99")
    home = codex_home()
    config = home / "context-weather.json"
    if config.is_symlink():
        raise SystemExit("Refused symlink")
    old = config.read_bytes() if config.exists() else None
    d = read_settings(home)
    if a.threshold is not None:
        d["threshold_percent"] = a.threshold
    if a.action is not None:
        d["action"] = a.action
    if a.language is not None:
        d["language"] = a.language
    if a.threshold is not None or a.action is not None or a.language is not None:
        if old is not None:
            backup = home / "context-weather-backups" / (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
            backup.mkdir(mode=0o700, parents=True)
            with (backup / "context-weather.json").open("xb") as f:
                f.write(old)
        if (config.read_bytes() if config.exists() else None) != old:
            raise SystemExit("Concurrent change: stopped")
        atomic_json(config, dict(version=1, **d))
        assert read_settings(home) == d
    print(json.dumps(d, ensure_ascii=False))
