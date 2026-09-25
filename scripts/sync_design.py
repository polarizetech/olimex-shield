#!/usr/bin/env python3
"""sync_design.py -- refresh apps/web/vendor/design from the upstream design system.

    python3 scripts/sync_design.py --from /path/to/design

The workbench ships a COPY so this repo runs on its own. Never edit the copy here; change the
design system upstream and sync. `apps/web/dev_check.py` fails when the copy drifts from an
upstream checkout it can find beside this repo.
"""

import argparse
import shutil
from pathlib import Path

DEST = Path(__file__).resolve().parents[1] / "apps" / "web" / "vendor" / "design"
FILES = ("design.css", "design.js", "tokens.json", "icons/polarize-icons.svg")

ap = argparse.ArgumentParser()
ap.add_argument("--from", dest="src", required=True)
src = Path(ap.parse_args().src).expanduser().resolve()
if not (src / "design.css").is_file():
    raise SystemExit(f"{src} is not a design system checkout (no design.css)")
for f in FILES:
    (DEST / f).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / f, DEST / f)
(DEST / "fonts").mkdir(parents=True, exist_ok=True)
for font in (src / "fonts").iterdir():
    if font.suffix in (".woff2", ".txt"):
        shutil.copy2(font, DEST / "fonts" / font.name)
print(f"synced {len(FILES)} files and fonts from {src}")
