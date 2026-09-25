#!/usr/bin/env python3
"""placement.py — WHERE DO THE ELECTRODES GO? As a picture, not a paragraph.

ONE JOB: turn a montage (role -> named body site) into a labelled diagram you can hold next to a
hand and copy. It owns the body maps and the rendering. It does NOT own what the montage should be
-- a scalp montage advisor, an ECG lead choice or a peripheral-montage protocol decides that.
This draws whatever they decide.

WHY IT IS ITS OWN MODULE AND NOT PART OF THE BRIDGE
    Several consumers describe electrode positions (10-20 scalp coordinates on a unit sphere,
    Einthoven limb leads as prose, hand sites as prose) and none of them can draw one. Putting
    the drawing in the bridge would have given the process that owns the serial port a job that
    has nothing to do with the port.

THE DEPENDENCY RUNS ONE WAY, deliberately: consumers call this; this imports nothing from them.
    Scalp positions are PASSED IN rather than duplicated, because the atlas's `electrodes.py` is
    the single source of truth for the 10-20 system and a second copy would drift. This module
    supplies the head outline and the projection; the caller supplies the coordinates.

THE HONESTY RULE, and it is the reason this file can refuse
    A diagram that omits a site the montage named, or shows one it did not, is WORSE THAN NO
    DIAGRAM -- someone will place an electrode from the picture. So `render()` raises on an unknown
    site rather than dropping it, and raises if the montage has no ground, because a missing ground
    is the single commonest reason a recording is all mains hum.

    The maps themselves are SCHEMATIC and say so: `registered_to` is null in bodymaps.json and
    stays null. Recognisable, not measured.

Stdlib only. No build step. `placement.js` renders the same thing in a browser from the same JSON.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAPS = json.loads((HERE / "bodymaps.json").read_text())

# Role -> how it is drawn. Colour is a fallback: the SHAPE and the printed role carry the meaning,
# so the diagram survives colour-blindness and a greyscale print. Same rule as the design system's
# badges -- hue is never load-bearing.
ROLE_STYLE = {
    # Glyphs are ASCII ON PURPOSE. The first version used typographic characters and they rendered
    # as mojibake the moment the SVG was embedded in a page without a charset declaration -- which
    # is exactly how a consumer will embed it. A diagram that garbles its own labels in the most
    # likely usage is not robust, and the cost of avoiding it is nil.
    "active": {"shape": "circle", "fill": "#c2410c", "text": "+", "order": 0},
    "reference": {"shape": "square", "fill": "#0e7490", "text": "-", "order": 1},
    "ground": {"shape": "triangle", "fill": "#3f6212", "text": "GND", "order": 2},
    "sham": {"shape": "dashed-circle", "fill": "none", "text": "sham", "order": 3},
    "aux": {"shape": "diamond", "fill": "#7c3aed", "text": "aux", "order": 4},
    "marker": {"shape": "dot", "fill": "#a16207", "text": "dot", "order": 5},
}


class PlacementError(ValueError):
    pass


def maps():
    return {
        k: {"label": v["label"], "orientation": v["orientation"], "sites": sorted(v["landmarks"])}
        for k, v in MAPS["maps"].items()
    }


def get_map(map_id, mirror=False):
    if map_id not in MAPS["maps"]:
        raise PlacementError(f"unknown body map {map_id!r}; have {sorted(MAPS['maps'])}")
    m = json.loads(json.dumps(MAPS["maps"][map_id]))  # deep copy; callers may mutate
    if mirror:
        w = m["view_box"][2]
        for lm in m["landmarks"].values():
            lm["x"] = w - lm["x"]
            lm["label_dx"] = -lm["label_dx"]
            lm["anchor"] = {"start": "end", "end": "start"}.get(lm["anchor"], lm["anchor"])
        m["_mirrored"] = True
        m["label"] = (
            m["label"].replace("Right", "Left")
            if "Right" in m["label"]
            else m["label"] + " (mirrored)"
        )
        m["orientation"] = m["orientation"].replace("LEFT", "RIGHT").replace("right", "left")
    return m


def sites(map_id):
    return sorted(MAPS["maps"][map_id]["landmarks"]) if map_id in MAPS["maps"] else []


def _tri(x, y, r):
    return f"{x},{y - r} {x - r * 0.87},{y + r * 0.5} {x + r * 0.87},{y + r * 0.5}"


def _diamond(x, y, r):
    return f"{x},{y - r} {x + r},{y} {x},{y + r} {x - r},{y}"


FONT_SIZE = 10
# Mean glyph advance for this sans stack at font-size 1, measured off a render rather than guessed.
# Only used to SIZE THE CANVAS, never to position anything, so a few percent of error is harmless
# and always errs toward extra whitespace.
CHAR_ADVANCE = 0.55


def _label_width(text):
    return len(text) * CHAR_ADVANCE * FONT_SIZE


def _gutters(montage, lm):
    """How much room the labels actually need on each side. A FIXED gutter was the first attempt
    and it clipped the longest label ("GROUND / ulnar styloid (wrist)") on both the hand maps --
    the picture has to fit the words, not the other way round."""
    left = right = 24.0
    for e in montage:
        p_ = lm[e["site"]]
        text = f"{e['role'].upper()} / {e['site']}" if e.get("role") else e["site"]
        w = _label_width(text)
        tip = p_["x"] + p_["label_dx"]
        if p_["anchor"] == "end":
            left = max(left, -(tip - w) + 12)
        else:
            right = max(right, tip + w + 12)
    return left, right


def label_boxes(montage, map_id="hand-dorsal-right", mirror=False):
    """Where each label's text actually lands, in view-box units.

    Same estimate `_gutters` already uses, so the two cannot disagree about how wide a label is.
    """
    m = get_map(map_id, mirror=mirror)
    lm = m["landmarks"]
    out = []
    for e in montage:
        site = e["site"]
        if site not in lm:
            continue
        p_ = lm[site]
        text = f"{e['role'].upper()} / {site}" if e.get("role") else site
        w = _label_width(text)
        x = p_["x"] + p_["label_dx"]
        y = p_["y"] + p_["label_dy"]
        anchor = p_["anchor"]
        x0 = x - w if anchor == "end" else (x - w / 2 if anchor == "middle" else x)
        out.append(
            {
                "site": site,
                "text": text,
                "x0": x0,
                "x1": x0 + w,
                "y0": y - FONT_SIZE * 0.6,
                "y1": y + FONT_SIZE * 0.6,
            }
        )
    return out


def label_collisions(montage, map_id="hand-dorsal-right", mirror=False):
    """Pairs of labels whose text boxes overlap.

    A diagram whose captions sit on top of each other is unreadable in exactly the place it
    matters — beside the electrode. This was found by LOOKING at a rendered head map (two labels
    printed over one another) rather than by any test, which is why it is a function now.
    """
    boxes = label_boxes(montage, map_id, mirror)
    hits = []
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            if a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["y0"] < b["y1"] and b["y0"] < a["y1"]:
                hits.append((a["site"], b["site"]))
    return hits


def render(
    montage, map_id="hand-dorsal-right", mirror=False, title=None, width=560, require_ground=True
):
    """Montage -> a self-contained SVG string.

    `montage` is a list of {role, site, note?} — the shape the scalp montage advisor, ECG lead
    definitions and peripheral montages already use.
    """
    m = get_map(map_id, mirror=mirror)
    lm = m["landmarks"]
    roles = [e.get("role") for e in montage]

    if require_ground and not any(r in ("ground",) for r in roles):
        raise PlacementError(
            "this montage has no GROUND. A missing ground is the commonest reason a recording is "
            "nothing but mains hum, so a diagram without one is refused rather than drawn. Pass "
            "require_ground=False only if the hardware genuinely has no ground connection."
        )

    unknown = [e["site"] for e in montage if e["site"] not in lm]
    if unknown:
        raise PlacementError(
            f"{map_id} has no landmark for {unknown!r}. A diagram that silently drops a site is "
            f"worse than no diagram — someone will place an electrode from it. Known sites: "
            f"{sorted(lm)}"
        )

    vb = list(m["view_box"])
    need_l, need_r = _gutters(montage, lm)
    pad_l = max(0.0, need_l)
    pad_r = max(0.0, need_r - vb[2])
    vb = [vb[0] - pad_l, vb[1] - 10, vb[2] + pad_l + pad_r, vb[3] + 20]
    scale = width / vb[2]
    height = round(vb[3] * scale)
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{" ".join(map(str, vb))}" '
        f'width="{width}" height="{height}" role="img" '
        f'aria-label="{_esc(title or m["label"])} - electrode placement">'
    ]
    out.append(f"<title>{_esc(title or m['label'])}</title>")
    # currentColor so the diagram inherits the page's theme instead of fighting it.
    for d in m["outline"]:
        out.append(
            f'<path d="{d}" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round" opacity="0.55"/>'
        )

    for e in sorted(montage, key=lambda x: ROLE_STYLE.get(x.get("role"), {}).get("order", 9)):
        role, site = e.get("role"), e["site"]
        st = ROLE_STYLE.get(role, ROLE_STYLE["marker"])
        p = lm[site]
        x, y, r = p["x"], p["y"], 9
        if st["shape"] == "square":
            out.append(
                f'<rect x="{x - r}" y="{y - r}" width="{2 * r}" height="{2 * r}" rx="2" '
                f'fill="{st["fill"]}" stroke="#000" stroke-opacity=".35"/>'
            )
        elif st["shape"] == "triangle":
            out.append(
                f'<polygon points="{_tri(x, y, r + 1)}" fill="{st["fill"]}" '
                f'stroke="#000" stroke-opacity=".35"/>'
            )
        elif st["shape"] == "diamond":
            out.append(
                f'<polygon points="{_diamond(x, y, r + 1)}" fill="{st["fill"]}" '
                f'stroke="#000" stroke-opacity=".35"/>'
            )
        elif st["shape"] == "dashed-circle":
            out.append(
                f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="currentColor" '
                f'stroke-width="2" stroke-dasharray="3 3"/>'
            )
        elif st["shape"] == "dot":
            out.append(f'<circle cx="{x}" cy="{y}" r="4" fill="{st["fill"]}"/>')
        else:
            out.append(
                f'<circle cx="{x}" cy="{y}" r="{r}" fill="{st["fill"]}" '
                f'stroke="#000" stroke-opacity=".35"/>'
            )
        # The role is PRINTED next to every marker, so the picture does not depend on colour.
        label = f"{role.upper()} / {site}" if role else site
        tx, ty = x + p["label_dx"], y + p["label_dy"]
        # A leader line, because once labels move out to the gutter it stops being obvious which
        # marker each one belongs to -- which is the whole point of the picture.
        out.append(
            f'<line x1="{x}" y1="{y}" x2="{tx}" y2="{ty}" stroke="currentColor" '
            f'stroke-width="0.75" opacity="0.35"/>'
        )
        out.append(
            f'<text x="{tx}" y="{ty}" text-anchor="{p["anchor"]}" '
            f'font-size="{FONT_SIZE}" font-family="Inter,system-ui,sans-serif" fill="currentColor" '
            f'paint-order="stroke" stroke="context-fill" stroke-width="0" '
            f'dominant-baseline="middle">{_esc(label)}</text>'
        )
    out.append("</svg>")
    return "\n".join(out)


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def checklist(montage, map_id="hand-dorsal-right", mirror=False):
    """The words that go beside the picture: one line per connection, plus each site's own note."""
    m = get_map(map_id, mirror=mirror)
    lm = m["landmarks"]
    rows = []
    for e in sorted(montage, key=lambda x: ROLE_STYLE.get(x.get("role"), {}).get("order", 9)):
        site = e["site"]
        rows.append(
            {
                "role": e.get("role"),
                "site": site,
                "glyph": ROLE_STYLE.get(e.get("role"), ROLE_STYLE["marker"])["text"],
                "where": lm.get(site, {}).get("note"),
                "note": e.get("note"),
            }
        )
    return {
        "map": map_id,
        "label": m["label"],
        "orientation": m["orientation"],
        "mirrored": bool(mirror),
        "rows": rows,
        "schematic_warning": MAPS["note"],
    }
