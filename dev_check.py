#!/usr/bin/env python3
"""dev_check.py -- the repo's gate. Runs every suite via scripts/check.py."""

import runpy
import sys
from pathlib import Path

sys.argv = [str(Path(__file__).resolve().parent / "scripts" / "check.py")]
runpy.run_path(sys.argv[0], run_name="__main__")
