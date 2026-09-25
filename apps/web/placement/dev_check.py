#!/usr/bin/env python3
"""dev_check.py — placement self-tests.

Most of these pin REFUSALS, because the failure that matters is not an ugly diagram: it is a
diagram that quietly disagrees with the montage it claims to draw. Someone places an electrode
from the picture.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import placement as P

P_, F_, FAIL = 0, 0, []


def ok(cond, msg):
    global P_, F_
    if cond:
        P_ += 1
    else:
        F_ += 1
        FAIL.append(msg)
        print("  FAIL", msg)


def throws(fn):
    try:
        fn()
        return False
    except P.PlacementError:
        return True


HAND = [
    {"role": "active", "site": "FDI belly"},
    {"role": "reference", "site": "2nd MCP joint"},
    {"role": "ground", "site": "ulnar styloid (wrist)"},
    {"role": "aux", "site": "index fingertip"},
]

# ---------------------------------------------------------------- the data is honest about itself
raw = json.loads((Path(__file__).parent / "bodymaps.json").read_text())
ok(raw["registered_to"] is None, "the maps declare they are registered to no anatomical frame")
ok(
    "SCHEMATIC" in raw["note"] and "nothing here is measured" in raw["note"].lower(),
    "…and say in words that they are schematic and nothing is measured",
)
for mid, m in raw["maps"].items():
    ok(bool(m["outline"]) and bool(m["landmarks"]), f"{mid}: has an outline and landmarks")
    ok(
        "orientation" in m and len(m["orientation"]) > 20,
        f"{mid}: states which way round it is — a mirrored diagram is a wrong diagram",
    )
    for name, lmk in m["landmarks"].items():
        ok(
            all(k in lmk for k in ("x", "y", "label_dx", "label_dy", "anchor")),
            f"{mid}/{name}: fully specified",
        )
        ok(
            bool(lmk.get("note")),
            f"{mid}/{name}: says in words where it is, not only where it draws",
        )
        # A map describes PLACES. Baking a role into a landmark note produces a wrong caption the
        # moment the same site is reused for another role — the sham hand read "GROUND goes here".
        ok(
            not any(r in lmk["note"].upper() for r in ("GROUND", "ACTIVE", "REFERENCE")),
            f"{mid}/{name}: the note describes the PLACE, not what goes there",
        )
        ok(
            0 <= lmk["x"] <= m["view_box"][2] and 0 <= lmk["y"] <= m["view_box"][3],
            f"{mid}/{name}: sits inside the body's own box",
        )
    # Every landmark drawn at once is the worst case, and it is the case a consumer reaches by
    # asking for a full montage. Two captions printed on top of each other are unreadable exactly
    # where it matters — beside the electrode. Found by LOOKING at a rendered head map, not by any
    # test, and it turned out `torso-front` had been doing it since it was written.
    _all = [
        {"role": "ground" if i == 0 else "marker", "site": s_} for i, s_ in enumerate(P.sites(mid))
    ]
    _hits = P.label_collisions(_all, mid)
    ok(not _hits, f"{mid}: no two labels overlap when every landmark is drawn ({_hits})")

# ----------------------------------------------------------------------- the 10-20 head sites ---
head = raw["maps"]["head-lateral-right"]
hl = head["landmarks"]
ok("the head map has an Oz site", "Oz (occipital)" in hl)
ok(
    "…and says it is an ESTIMATED 10-20 position, not a measured one",
    "ESTIMATED 10-20" in head["orientation"] and "estimated 10-20" in raw["note"].lower(),
)
ok(
    "the inion is a measuring landmark, not a site",
    "not an electrode site" in hl["inion"]["note"],
)
_oz, _in, _cz = hl["Oz (occipital)"], hl["inion"], hl["Cz (vertex)"]
_d = lambda a, b: ((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2) ** 0.5  # noqa: E731
ok(
    "Oz sits above the inion and much nearer it than Cz (10% vs 50% of nasion-inion)",
    _oz["y"] < _in["y"] and _d(_oz, _in) < 0.5 * _d(_oz, _cz),
)
ok("Oz's note gives the 10% rule", "10%" in _oz["note"] and "inion" in _oz["note"])
ok(
    "Cz's side-to-side measurement uses the preauricular points, not the ear canals",
    "preauricular" in _cz["note"] and "between the two ear canals" not in _cz["note"],
)

# ------------------------------------------------------------- the surface-EMG bipolar pair ---
hand = raw["maps"]["hand-dorsal-right"]["landmarks"]
_p, _q = hand["FDI belly, proximal"], hand["FDI belly, distal"]
ok(
    "the FDI bipolar pair is two sites over the same belly, a short step apart",
    8 <= _d(_p, _q) <= 30 and _d(_p, hand["FDI belly"]) < 25 and _d(_q, hand["FDI belly"]) < 25,
)
ok("…and the proximal end is nearer the wrist than the distal end", _p["y"] > _q["y"])
ok("…with SENIAM's spacing rule stated", "SENIAM" in _p["note"] and "20 mm" in _p["note"])
_emg = [
    {"role": "active", "site": "FDI belly, distal"},
    {"role": "reference", "site": "FDI belly, proximal"},
    {"role": "ground", "site": "ulnar styloid (wrist)"},
]
ok("the bipolar EMG montage draws with no label collisions", not P.label_collisions(_emg))

# ------------------------------------------------------------------------------- the refusals ---
ok(
    throws(lambda: P.render([{"role": "active", "site": "FDI belly"}], "hand-dorsal-right")),
    "a montage with NO GROUND is refused — the commonest cause of an all-mains recording",
)
ok(
    throws(lambda: P.render(HAND + [{"role": "active", "site": "elbow"}], "hand-dorsal-right")),
    "an unknown site is refused rather than silently dropped from the picture",
)
ok(throws(lambda: P.render(HAND, "no-such-map")), "an unknown body map is refused")
ok(
    P.render(
        [{"role": "active", "site": "FDI belly"}, {"role": "reference", "site": "2nd MCP joint"}],
        "hand-dorsal-right",
        require_ground=False,
    ),
    "…but require_ground=False is available for hardware that genuinely has no ground",
)

# --------------------------------------------------------------------------------- the render ---
svg = P.render(HAND, "hand-dorsal-right", title="Arm A")
ok(svg.startswith("<svg") and svg.rstrip().endswith("</svg>"), "renders a complete SVG")
ok('xmlns="http://www.w3.org/2000/svg"' in svg, "…namespaced, so it works as a standalone file")
ok("currentColor" in svg, "…and inherits the page's theme instead of fighting it")
ok('role="img"' in svg and "aria-label" in svg, "…with an accessible name")
for e in HAND:
    ok(e["site"] in svg, f"every montage site appears in the drawing: {e['site']}")
    ok(
        e["role"].upper() in svg,
        f"…labelled with its ROLE, so colour is never load-bearing: {e['role']}",
    )

ok(
    svg.count("<line") >= len(HAND),
    "each marker has a leader line to its label — once labels move to the gutter, which marker "
    "they belong to stops being obvious",
)

# Non-ASCII in a label renders as mojibake the moment a consumer embeds the SVG in a page with no
# charset declaration, which is exactly how it will be embedded.
body = re.sub(r"<title>.*?</title>", "", svg, flags=re.S)
ok(all(ord(c) < 128 for c in body), "the rendered SVG is pure ASCII — no mojibake in a naive embed")

# The canvas must fit the WORDS, not the other way round: a fixed gutter clipped the longest label.
vb = [float(x) for x in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
ok(vb[0] < 0, "the viewBox is extended left to hold labels outside the body")
longest = max(f"{e['role'].upper()} / {e['site']}" for e in HAND)
ok(
    vb[2] > raw["maps"]["hand-dorsal-right"]["view_box"][2] + P._label_width(longest),
    "…and is sized from the actual label widths, so the longest one cannot clip",
)

# -------------------------------------------------------------------------------- mirroring -----
right = P.render(HAND, "hand-dorsal-right")
left = P.render(HAND, "hand-dorsal-right", mirror=True)
ok(right != left, "mirroring changes the drawing")
mr = P.get_map("hand-dorsal-right")
ml = P.get_map("hand-dorsal-right", mirror=True)
w = mr["view_box"][2]
ok(
    all(abs(ml["landmarks"][k]["x"] - (w - v["x"])) < 1e-9 for k, v in mr["landmarks"].items()),
    "every landmark mirrors about the body's midline",
)
ok(
    all(ml["landmarks"][k]["y"] == v["y"] for k, v in mr["landmarks"].items()),
    "…and nothing moves vertically",
)
ok(
    "Left" in ml["label"],
    "the mirrored map RENAMES itself — a left hand labelled 'right' is the "
    "exact error this tool exists to prevent",
)
ok(ml["orientation"] != mr["orientation"], "…and its orientation sentence flips too")

# ------------------------------------------------------------------------------- the checklist --
c = P.checklist(HAND, "hand-dorsal-right")
ok(
    [r["role"] for r in c["rows"]] == ["active", "reference", "ground", "aux"],
    "the checklist is ordered active, reference, ground — the order you connect them",
)
ok(all(r["where"] for r in c["rows"]), "every row says in words where the site is")
ok(c["schematic_warning"], "the checklist carries the schematic warning with it")
ok(
    P.checklist(HAND, "hand-dorsal-right", mirror=True)["mirrored"] is True,
    "the checklist knows when it describes a mirrored diagram",
)

# --------------------------------------------------------------------- one-way dependency -------
# Checked against IMPORT STATEMENTS, not raw text: the docstring names its consumers on purpose,
# and a substring search on the whole file would fail for the documentation rather than the code.
src = (Path(__file__).parent / "placement.py").read_text()
imports = [
    line.strip()
    for line in src.splitlines()
    if line.strip().startswith(("import ", "from ")) and "#" not in line.split("import")[0]
]
ok(
    all(
        not any(c in line for c in ("electrodes", "eeg", "auditory", "hardware", "modes"))
        for line in imports
    ),
    f"placement.py imports none of its consumers — the dependency runs one way, and the 10-20 "
    f"truth stays with the atlas rather than being copied here (imports: {imports})",
)
ok(
    all("numpy" not in line and "scipy" not in line for line in imports),
    "…and stays stdlib-only, so any project can render a diagram with no environment",
)

print(f"\ndev_check {P_}/{P_ + F_}")
if FAIL:
    print("\n".join("  - " + f for f in FAIL))
sys.exit(1 if F_ else 0)
