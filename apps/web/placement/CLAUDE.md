# CLAUDE.md — electrode-placement

**One job: turn a montage into a labelled picture you can hold next to a hand and copy.**

`python3 dev_check.py`. Stdlib only, no build step, no venv. Wiring a project in →
[`INTEGRATION.md`](INTEGRATION.md).

## Why it is its own module and not part of the bridge

Several consumers describe electrode positions (10-20 scalp coordinates on a unit sphere,
Einthoven limb leads as prose, hand sites as prose) and **none of them could draw one**. Putting
the drawing in the bridge would give the process that owns the serial port a job that has nothing
to do with the port.

**The dependency runs one way and `dev_check.py` asserts it** (against import statements, not raw
text — the docstring names its consumers on purpose). Scalp coordinates are **passed in** rather
than duplicated: a 10-20 coordinate table belongs to whichever tool owns the scalp model, and a
second copy would drift. This module supplies the outline and the drawing; the caller supplies
the positions.

## What it refuses, and why refusing is the point

**A diagram that omits a site the montage named, or shows one it did not, is worse than no
diagram** — someone will place an electrode from the picture. So:

- an **unknown site raises** rather than being silently dropped;
- a montage with **no ground raises**, because a missing ground is the commonest reason a recording
  is nothing but mains hum (`require_ground=False` exists for hardware that genuinely has none);
- an unknown body map raises.

## Honesty properties, enforced by tests

- **`registered_to` is `null` and stays null.** These are schematics: recognisable, drawn by eye
  against anatomy references, not measured and not to scale.
- **The role is printed beside every marker**, and the shapes differ (circle / square / triangle /
  diamond / dashed). Colour is never load-bearing, so the diagram survives colour-blindness and a
  greyscale print — the same rule the design system applies to its badges.
- **A mirrored map renames itself.** A left hand labelled "right" is the exact error this tool
  exists to prevent, so `get_map(mirror=True)` rewrites both the label and the orientation sentence.
- **Every map states which way round it is** in words, because a diagram whose orientation you have
  to guess is one you can mirror by accident.
- **A landmark note describes the PLACE, never the role.** Caught in review: the ulnar-styloid note
  read "GROUND goes here", which produced a wrong caption the moment the same site was drawn on the
  *sham* hand. The map says where the place is; the montage says what goes there.
- **Head sites are estimated 10-20 positions.** The head map says so in its orientation sentence
  and the file note, and a montage names the 10-20 site (Oz, Cz), never a measuring landmark: the
  inion and nasion are where the tape goes, not where an electrode goes. Oz is drawn 10% of the
  nasion-inion arc above the inion; Cz's note uses the preauricular points for the side-to-side
  measurement, as 10-20 does.
- **The surface-EMG pair is bipolar over the belly (SENIAM), not belly-tendon.** Belly-tendon is
  the nerve-conduction convention. `FDI belly, distal` / `FDI belly, proximal` lie along the
  fibres; SENIAM's 20 mm spacing is capped at a quarter of the muscle length, ~10-15 mm on FDI.

## Two things measured rather than assumed

1. **A fixed label gutter clips.** The first render put labels in a fixed 118-unit margin and the
   longest one (`GROUND / ulnar styloid (wrist)`) ran off both hand maps. The canvas is now sized
   from the actual label widths — **the picture fits the words, not the other way round.**
2. **Typographic glyphs become mojibake in the most likely embed.** `·`, `＋` and `⏚` rendered as
   `Â·` the moment the SVG was dropped into a page with no charset declaration, which is exactly
   how a consumer will use it. Labels are now **pure ASCII**, asserted by a test.

## Not done

- **`placement.js` does not exist.** Rendering is server-side only, which is right while every
  consumer has a Python server, and it means there is no JS/Python parity to keep. The trigger for
  a port is a consumer with no server.
- **No top-down scalp map yet.** There is a lateral head map with a handful of estimated 10-20
  sites; a full 10-20 projection is the obvious next map. Nothing here blocks it.
- **Nothing is validated against an anatomical reference.** Landmarks were placed by eye. The tests
  check self-consistency and the declared honesty properties; they cannot check that the FDI belly
  is in the right place, and a user who does not already know roughly where it is should not learn
  it from here.
