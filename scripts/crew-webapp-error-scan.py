#!/usr/bin/env python3
"""Pull recent webapp JSON logs and summarize errors."""
from __future__ import annotations

import json
import subprocess
import sys


def main() -> None:
    since = sys.argv[1] if len(sys.argv) > 1 else "2m"
    r = subprocess.run(
        [
            "docker",
            "logs",
            "docker-structs-guild-structs-webapp-1",
            "--since",
            since,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (r.stdout or "") + (r.stderr or "")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            low = line.lower()
            if any(x in low for x in ("error", "critical", "exception", "authorize", "oidc")):
                print("RAW", line[:600])
            continue
        lvl = o.get("level_name") or ""
        msg = o.get("message") or ""
        interesting = lvl in ("ERROR", "CRITICAL", "WARNING") or any(
            x in msg.lower() for x in ("oidc", "authorize", "exception", "error", "critical")
        )
        if not interesting:
            continue
        if "User Deprecated" in msg:
            continue
        print(lvl, msg[:400])
        ex = (o.get("context") or {}).get("exception") or {}
        if ex:
            print(" ", ex.get("class"), (ex.get("message") or "")[:500])
            print(" ", "file", ex.get("file"), "line", ex.get("line"))
            trace = ex.get("trace")
            if isinstance(trace, list):
                for frame in trace[:8]:
                    print("   ", frame.get("file"), frame.get("line"), frame.get("function") or frame.get("class"))


if __name__ == "__main__":
    main()
