"""readouts.py -- WHAT the electrodes are measuring, and whether this front end can carry it.

STDLIB ONLY (it is imported by serve.py). Reads the board's constants from
`apps/server/rig.py` and never restates them. Ported from an earlier internal project, where
it was written.

*** THE JOB THIS FILE DOES, AND WHY IT RUNS BEFORE A SESSION RATHER THAN AFTER ONE. ***

The operator's own examples were "EDA on the left hand with a visual stimulus" and "ECG for
HRV with silent visualisations". Those are DIFFERENT INSTRUMENTS wearing the same two
electrodes, and the Olimex front end treats them very differently -- one of them it largely
destroys. Finding that out from a flat result four minutes into a session is the expensive
way; `gate()` is four lines of arithmetic over a constant already on disk.

    The viability gate, Q1: "is the readout in the analog band at all?"
    Two earlier experiments were built in full and then killed by that question. This
    workbench asks it first.

*** WHAT EACH READOUT CARRIES BESIDES A BAND. ***

The settling window, and above all the CONFUSABLES: the things that produce exactly the reading
a response would, on this site, and cannot be told apart from one on one channel. They are a
fact about the electrode and the body, which is why they live here and are shown in the guide.

*** A READOUT MAY NOT CARRY AN EXPECTED RESULT. ***

A rule borrowed from stimulus description: a description of what was
delivered that also says what it should do has smuggled the hypothesis into the only thing
the analysis is allowed to see. There is no `expects` field here and `dev_check.py` fails if
one appears.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

import rig

SCHEMA = "olimex-shield.readout/1"


class ReadoutError(ValueError):
    pass


#: Each readout declares the frequency at which its INFORMATIVE feature lives -- not the
#: band it is conventionally filtered to. For an event-related readout that is
#: 1 / (2 * feature duration): a 5 s skin-conductance rise is a ~0.1 Hz feature however
#: slowly the underlying level wanders.
READOUTS = {
    "eeg": {
        "label": "EEG — cortical potential",
        # Estimated 10-20 positions: drawn by eye and found on the head with a tape, never
        # measured by this app. The label says so, because "Oz" reads as a measured fact.
        "site_examples": [
            "Oz–Cz (occipital, visual; estimated 10-20 positions)",
            "Fz–mastoid (frontal; estimated 10-20 positions)",
        ],
        "band_hz": (1.0, 40.0),
        "feature_hz": 10.0,
        "feature_note": "alpha and the evoked complex sit inside the passband",
        "settling_s": 120.0,
        "settling_note": (
            "a fresh gel joint drifts while the electrolyte wets the skin; "
            "the first minutes are the joint, not the cortex"
        ),
        # The sites are placement/'s OWN vocabulary, not free text: that module
        # raises on a site it does not know, which is exactly the behaviour you want when
        # someone is about to place an electrode from your picture.
        "map_id": "head-lateral-right",
        #
        # The active electrode is Oz, 10% of the nasion-inion distance above the inion. The
        # inion itself is a MEASURING landmark (bodymaps.json says so), not an electrode site;
        # an earlier version advertised "Oz–Cz" and put the electrode on the inion.
        "montage": [
            {
                "role": "active",
                "site": "Oz (occipital)",
                "note": "estimated 10-20 position, not measured -- find it with a tape",
            },
            {
                "role": "reference",
                "site": "Cz (vertex)",
                "note": "estimated 10-20 position, not measured -- find it with a tape",
            },
            {"role": "ground", "site": "M2 (right mastoid)"},
        ],
        "confusables": (
            "an eye blink, which is larger than any cortical response and lands frontally",
            "an eye movement (the corneoretinal dipole)",
            "jaw and neck EMG, which looks like broadband activation",
            "electrode drift as the gel dries",
            "60 Hz mains and its intermodulation with a poor contact",
            "the operator's own keystroke, if the subject is the operator",
        ),
        "controls": (
            "a matched block with no stimulus and the same tag cadence",
            "an EOG channel, or at minimum a video of the face",
        ),
    },
    "ecg": {
        "label": "ECG — cardiac, for rate and HRV",
        "site_examples": [
            "Lead I (right wrist – left wrist)",
            "Lead II (right wrist – left ankle)",
        ],
        "band_hz": (0.5, 40.0),
        "feature_hz": 1.1,
        "feature_note": "the R-R rate; HRV is a modulation OF it, not a band in the record",
        "settling_s": 60.0,
        "settling_note": "electrode polarisation settles over the first minute after contact",
        "map_id": "limbs-front",
        "montage": [
            {"role": "active", "site": "left wrist"},
            {"role": "reference", "site": "right wrist"},
            {"role": "ground", "site": "right ankle"},
        ],
        "confusables": (
            "a breath — respiratory sinus arrhythmia moves heart rate on its own, with no "
            "stimulus at all, and it is the single largest confound for any HRV reading",
            "a postural change or a limb movement",
            "a swallow or a cough",
            "EMG from the arm holding still",
            "60 Hz mains",
        ),
        "controls": (
            "a respiration belt or a paced-breathing block — WITHOUT one, an HRV change and "
            "a breathing change are the same measurement",
            "a matched block with no stimulus and the same tag cadence",
        ),
    },
    "emg": {
        "label": "EMG — muscle",
        "site_examples": [
            "FDI, bipolar along the fibres",
            "forearm flexor belly, bipolar along the fibres",
        ],
        "band_hz": (20.0, 40.0),
        "feature_hz": 40.0,
        "feature_note": (
            "surface-EMG energy lies mostly between 20 and 150+ Hz (peaking around 50–150 Hz) "
            "and the board's analog low-pass stops at 40 Hz, so it removes most of the EMG band. "
            "What survives is the very bottom edge: onset, offset and gross activation, "
            "not EMG amplitude or spectral measures such as median frequency"
        ),
        "settling_s": 30.0,
        "settling_note": "electrode settling; muscle needs no acclimation",
        "map_id": "hand-dorsal-right",
        # *** BIPOLAR OVER THE BELLY (SENIAM), NOT BELLY-TENDON. ***
        # Belly-tendon (active on the belly, reference on a bony/tendinous point) is the
        # nerve-conduction convention for a compound muscle action potential under stimulation.
        # For VOLUNTARY surface EMG the SENIAM recommendation is a bipolar pair on the belly, in
        # line with the fibres, 20 mm centre to centre -- and no more than a quarter of the
        # muscle's length, which on the small FDI means ~10-15 mm. SENIAM's own site list covers
        # larger muscles; FDI is used here because it is the one on the hand map.
        "montage": [
            {
                "role": "active",
                "site": "FDI belly, distal",
                "note": "bipolar pair along the fibres (SENIAM), ~10-15 mm apart on this muscle",
            },
            {
                "role": "reference",
                "site": "FDI belly, proximal",
                "note": "same muscle, same line of fibres: both electrodes over the belly",
            },
            {"role": "ground", "site": "ulnar styloid (wrist)"},
        ],
        "confusables": (
            "any voluntary movement whatever, including shifting in the chair",
            "cardiac artefact if the site is on the trunk",
            "cable movement",
            "60 Hz mains, which sits inside the EMG band",
        ),
        "controls": ("a matched block with no stimulus", "a video of the limb"),
    },
}


#: *** WHY EDA IS NOT ON THE LIST, kept as a refusal rather than a silent absence. ***
#:
#: A readout that is simply missing reads as "nobody thought of it". This one was built,
#: gated, rendered and then REMOVED on 2026-09-08, and the arithmetic that killed it is worth
#: more than the option was. Two independent reasons, either sufficient:
REFUSED = {
    "eda": {
        "label": "EDA — electrodermal / skin conductance",
        "removed": "2026-09-08",
        "reasons": [
            (
                "THE BOARD IS NOT AN EDA AMPLIFIER. Skin conductance is measured by passing a "
                "small known current and reading a RESISTANCE. The SHIELD-EKG-EMG is a "
                "high-impedance differential VOLTAGE amplifier with no current source, so what "
                "it records at those electrodes is skin POTENTIAL (EDP) -- a related but "
                "different signal wearing the wrong name. No amount of processing converts one "
                "into the other; it needs different hardware."
            ),
            (
                "AND THE FRONT END DIFFERENTIATES IT ANYWAY. A phasic skin-conductance response "
                "is a 1-5 s rise, i.e. a ~0.1 Hz feature, below the board's 0.16 Hz corner "
                "(tau = 0.995 s). What reaches the converter is the response's EDGE, not its "
                "level, and the true amplitude is not recoverable. `rig.carries(0.1)` returns "
                "`degraded` and the differentiation warning."
            ),
        ],
        "what_would_unrefuse_it": (
            "a constant-current source and a DC-coupled front end -- "
            "i.e. an actual EDA amplifier. This is a hardware "
            "purchase, not a code change."
        ),
    },
}


def get(key: str) -> dict:
    if key in REFUSED:
        r = REFUSED[key]
        raise ReadoutError(
            f"{key!r} is not offered on this rig, and that is a measured refusal rather than "
            f"an oversight. "
            + " ".join(r["reasons"])
            + f" What would change it: {r['what_would_unrefuse_it']}"
        )
    if key not in READOUTS:
        raise ReadoutError(f"unknown readout {key!r}; have {sorted(READOUTS)}")
    return READOUTS[key]


def gate(key: str) -> dict:
    """Can this front end carry this readout's informative feature? Answer BEFORE recording.

    Returns the per-frequency verdict for the feature and both band edges, so a readout that
    is fine in the middle and destroyed at one edge cannot read as simply 'reachable'.
    """
    r = get(key)
    lo, hi = r["band_hz"]
    probes = {
        "feature": rig.carries(r["feature_hz"]),
        "band_low_edge": rig.carries(lo),
        "band_high_edge": rig.carries(hi),
    }
    verdicts = [p["verdict"] for p in probes.values()]
    overall = (
        "unreachable"
        if probes["feature"]["verdict"] == "unreachable"
        else "degraded"
        if "unreachable" in verdicts or "degraded" in verdicts
        else "reachable"
    )
    out = {
        "schema": SCHEMA,
        "readout": key,
        "label": r["label"],
        "overall": overall,
        "probes": probes,
        "feature_note": r["feature_note"],
        "hp_tau_s": rig.HP_TAU_S,
        "source": rig.SOURCE,
    }
    if r.get("instrument_warning"):
        out["instrument_warning"] = r["instrument_warning"]
    # The differentiation warning, which is the one that catches people. A first-order
    # high-pass with tau ~1 s does not merely attenuate a slower feature -- it DIFFERENTIATES
    # it, so what reaches the converter is the feature's edge and not its plateau, and its
    # true amplitude is not recoverable from the record at any gain.
    if r["feature_hz"] < rig.FRONT_END_HP_HZ * 2:
        out["differentiated"] = (
            f"this readout's feature sits at {r['feature_hz']:g} Hz, at or below the "
            f"{rig.FRONT_END_HP_HZ:g} Hz corner (tau = {rig.HP_TAU_S:.3f} s). The front end "
            f"DIFFERENTIATES it: what is recorded is the feature's edge, not its level, and "
            f"the true amplitude is not recoverable. Deviation SHAPE and TIMING survive; "
            f"amplitude does not, and must not be quoted."
        )
    return out


def catalogue() -> list:
    out = []
    for k in READOUTS:
        g = gate(k)
        out.append(
            {
                "key": k,
                "label": READOUTS[k]["label"],
                "site_examples": READOUTS[k]["site_examples"],
                "band_hz": list(READOUTS[k]["band_hz"]),
                "montage": READOUTS[k]["montage"],
                "map_id": READOUTS[k]["map_id"],
                "overall": g["overall"],
                "differentiated": g.get("differentiated"),
                "instrument_warning": g.get("instrument_warning"),
            }
        )
    return out
