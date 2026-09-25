# INTEGRATION.md — drawing your montage

## 1. Import it

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path("apps/web/placement").resolve()))  # wherever this folder lives
import placement
```

## 2. Hand it the montage you already have

`placement` wants a list of `{role, site, note?}` — the shape `readouts.py` already uses for its
EEG, ECG and EMG montages.

```python
montage = [   # bipolar surface EMG over one belly, along the fibres (SENIAM)
    {"role": "active",    "site": "FDI belly, distal"},
    {"role": "reference", "site": "FDI belly, proximal"},
    {"role": "ground",    "site": "ulnar styloid (wrist)"},
]
svg  = placement.render(montage, "hand-dorsal-right", title="FDI, bipolar")
list_ = placement.checklist(montage, "hand-dorsal-right")
```

`render` returns a self-contained SVG string; drop it straight into a page. It draws in
`currentColor`, so it inherits your theme rather than fighting it.

**Roles:** `active` `reference` `ground` `sham` `aux` `marker`. Anything else draws as a plain dot.

## 3. Maps available

| id | For |
|---|---|
| `hand-dorsal-right` | hand/forearm sites — pass `mirror=True` for the left hand |
| `torso-front` | chest and hip sites |
| `limbs-front` | Einthoven limb leads |
| `head-lateral-right` | estimated 10-20 head sites (Oz, Cz, Fpz), mastoid, earlobe — `mirror=True` for the left |
| `neck-front` | sternocleidomastoid and sternal-notch sites |
| `stem-vertical` | a plant stem, for non-human recordings |

`placement.maps()` lists them with their sites; `placement.sites(map_id)` lists one map's.

## 4. Expect it to refuse

```python
placement.render([{"role": "active", "site": "FDI belly"}], "hand-dorsal-right")
# PlacementError: this montage has no GROUND …
```

Both refusals are deliberate — see CLAUDE.md. Pass `require_ground=False` only if your hardware
genuinely has no ground connection.

## 5. Adding a site or a map

Edit `bodymaps.json`. A landmark needs `x`, `y`, `label_dx`, `label_dy`, `anchor` and a `note`
saying **where the place is** — never what goes there, because the same site gets reused for
different roles and `dev_check.py` fails a note containing a role word. Put labels out in the
gutter; the canvas sizes itself around them.
