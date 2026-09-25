#!/usr/bin/env python3
"""check.py -- run every suite in this repo. Exit non-zero if any fails.

    python3 scripts/check.py

A suite that needs something missing (node, numpy, MNE) says SKIP in its own output; this
script prints each suite's last line so a skip is visible, never folded into a pass.
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUITES = [
    ("server", ["apps/server/dev_check.py"]),
    ("sessions", ["apps/server/dev_check_sessions.py"]),
    ("storage+bids", ["apps/server/dev_check_storage.py"]),
    ("signal-panel", ["apps/web/signal-panel/dev_check.py"]),
    ("placement", ["apps/web/placement/dev_check.py"]),
    ("workbench", ["apps/web/dev_check.py"]),
    ("docs+blog", ["scripts/check_docs.py"]),
]

failed = []
for name, args in SUITES:
    r = subprocess.run([sys.executable, *args], cwd=REPO, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip().splitlines()
    skips = [line.strip() for line in out if "SKIP" in line]
    print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {name:14s} {out[-1] if out else ''}")
    for s in skips:
        print(f"       {s}")
    if r.returncode:
        failed.append(name)
        print("\n".join("       " + line for line in out[-25:]))
sys.exit(1 if failed else 0)
