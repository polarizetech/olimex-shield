"""hookup.py -- the guide that opens BEFORE the port does. Stdlib only.

*** WHY THIS EXISTS AS ITS OWN STEP RATHER THAN AS TEXT ON THE PAGE. ***

An earlier internal ECG app established the pattern and paid for it: pressing Connect opens a
modal showing the montage's placements, the full prep list and the FULL safety list, and only
then is a port opened. Building it there shook out a **silent bypass** --
`if (!S.design) return connectBridge()` meant a slow fetch let Connect open the port without
ever showing the guide. So the rule here is in the code and in `dev_check_js.mjs`:

    THE GUIDE IS FETCHED FIRST, AND A FAILED FETCH DOES NOT CONNECT.

There is no path from the Connect button to `/bridge/open` that does not pass through a
rendered dialog the operator dismissed.

*** THE DIAGRAM IS `placement/`'s, NOT A HAND DRAWING. ***

That tool owns turning a montage (role -> named body site) into a labelled picture, and it
REFUSES more than it draws: an unknown site raises rather than being silently dropped, and a
**montage with no ground raises**, because a missing ground is the commonest reason a
recording is nothing but mains. Both refusals are exactly what you want when someone is about
to place an electrode from your picture. `readouts.py` therefore states its montages in that
tool's own site vocabulary rather than in free text.

*** THE SAFETY LIST IS FULL, NEVER CONDENSED. ***

A condensed safety notice is a DIFFERENT notice. The same list appears in the modal and
nowhere is it abbreviated for space.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "placement"))

import placement
import readouts

#: This is a hobby amplifier on a person. Every line is a refusal, and none is negotiable for
#: space. Sourced from the Olimex SHIELD-EKG-EMG documentation's own warnings and from the
#: standing rule in the root CLAUDE.md that subject safety is the one blocker that never
#: relaxes. The README carries the same list; `dev_check.py` pins its length and its key lines,
#: so a shortened copy fails rather than drifting.
SAFETY = [
    "This is NOT a medical device and nothing it shows is a diagnosis. If you are worried "
    "about your heart, your brain or your skin, this app is not the instrument to use.",
    "Run the board from a BATTERY-POWERED laptop, unplugged from mains. A mains-powered USB "
    "host puts your body between a wall socket and an electrode; the Olimex shield is not a "
    "medically isolated front end.",
    "Unplug EVERY mains-connected device from the laptop, not only the charger: an external "
    "monitor or HDMI cable, a powered USB hub or dock, an Ethernet cable, and any "
    "mains-powered audio interface or headphone amplifier used for stimuli. Each one is a "
    "path from mains, through the laptop, to the electrodes.",
    'If you cannot run on battery, a "properly isolated" power supply alone is NOT enough: '
    "isolate the USB data line too, with a USB isolator rated for patient connection (medical "
    "isolation, e.g. to IEC 60601-1). A general-purpose USB isolator is not a substitute.",
    "Never connect an electrode to anyone with an implanted pacemaker, ICD, or any other "
    "active implanted device.",
    "Never give current a path across the chest. While anything mains-referenced is connected, "
    "do not place electrodes on both arms or on both sides of the chest -- an arm-to-arm or "
    "side-to-side pair puts the heart in that path. That includes this app's own ECG limb "
    "leads: record them on battery only, with nothing else plugged in.",
    "Do not touch grounded metal -- a radiator, a tap, a desktop PC's case -- while you are "
    "wired up. It gives any fault current a return path through you.",
    "Do not place electrodes on broken skin, on a rash, or over a wound.",
    "Stop immediately if the skin stings, burns, itches or reddens under an electrode.",
    "This app applies no current and delivers no stimulation of any kind. It only listens. "
    "If any part of the rig ever produces a sensation, disconnect it.",
    "One person, one rig, one session. Do not connect two people to the same amplifier.",
]

#: Prep, in the order it actually has to happen. The last one is the one people skip.
#: `apps/server/validation/VALIDATION.md` measured the in-band 40 Hz figure across six captures
#: on this rig: 64-750 nV, an 11.7x spread. That spread is UNATTRIBUTED -- it was once put down
#: to electrode prep, but the one capture scored good-contact had the HIGHEST value, so the
#: sidecars do not support that. Good prep is still right; it is not what the data shows.
PREP = [
    (
        "Unplug the laptop, and everything plugged into it.",
        "Battery power removes the mains path through you and takes most of the 60 Hz with it. "
        "A monitor, dock, Ethernet cable or powered audio interface puts that path straight "
        "back. This is the single highest-value thing on this list and it takes two seconds.",
    ),
    (
        "Clean the skin.",
        "Wipe each site with alcohol and let it dry. Skin oil is an insulator; a clean site is "
        "the difference between a signal and a beautifully quiet recording of nothing.",
    ),
    (
        "Gel every electrode, including the ground.",
        "Use conductive electrode gel or fresh wet gel pads. Ultrasound gel is an ACOUSTIC "
        "coupling medium, not an ionic one, and the drift it causes looks like biology.",
    ),
    (
        "Place the GROUND first, and check it.",
        "A floating ground is the commonest cause of a record that is nothing but mains hum. "
        "The placement diagram refuses to draw a montage without one for that reason.",
    ),
    (
        "Place the pair, and dress the leads together.",
        "This is ONE differential channel: you are recording the difference between two places, "
        "so there is no 'the electrode'. Keep the leads short and run them side by side -- a "
        "loop of loose wire is an antenna.",
    ),
    (
        "Sit still and let it settle before recording.",
        "Every readout here declares its own settling window, and marks inside it are labelled "
        "and excluded from the count. Recording immediately means recording the joint.",
    ),
    (
        "Watch the plausibility check, not the trace.",
        "A trace can look perfectly plausible at the noise floor. The check is a heuristic on "
        "the signal (amplitude, mains share, alpha), not an impedance measurement. Measured on "
        "this rig across six captures, in-band power at 40 Hz spanned 64-750 nV -- an 11.7x "
        "range whose cause is not yet known: the one capture scored good-contact had the "
        "highest value. That spread dominates anything this app computes afterwards.",
    ),
]


def guide(readout_key: str = "eeg") -> dict:
    """Everything the modal shows. Raises rather than returning a partial guide.

    A guide missing its diagram, or showing a site the montage does not contain, is worse
    than no guide -- someone places an electrode from it.
    """
    r = readouts.get(readout_key)
    montage = r["montage"]
    map_id = r["map_id"]
    mirror = bool(r.get("mirror"))
    svg = placement.render(
        montage, map_id=map_id, mirror=mirror, title=f"{r['label']} — where the electrodes go"
    )
    check = placement.checklist(montage, map_id=map_id, mirror=mirror)
    collisions = placement.label_collisions(montage, map_id=map_id, mirror=mirror)
    gate = readouts.gate(readout_key)
    out = {
        "readout": readout_key,
        "label": r["label"],
        "site_examples": list(r["site_examples"]),
        "montage": montage,
        "map_id": map_id,
        "mirrored": mirror,
        "svg": svg,
        "checklist": check,
        # A diagram whose labels print on top of each other is unreadable exactly where it
        # matters, beside the electrode. The tool measures it; this passes the measurement on
        # rather than hoping.
        "label_collisions": collisions,
        "prep": [{"step": a, "why": b} for a, b in PREP],
        "safety": list(SAFETY),
        "settling_s": r["settling_s"],
        "settling_note": r["settling_note"],
        "front_end": {
            "overall": gate["overall"],
            "differentiated": gate.get("differentiated"),
            "instrument_warning": gate.get("instrument_warning"),
        },
        "confusables": list(r["confusables"]),
        "controls": list(r["controls"]),
        "not_a_medical_device": SAFETY[0],
    }
    return out
