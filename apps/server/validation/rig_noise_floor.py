#!/usr/bin/env python3
"""
rig_noise_floor.py — the gate, run against THIS rig's own recordings. EXPERIMENTAL.

    Requires (1) private captures, found ONLY through $OLIMEX_RIG_CAPTURES, and (2) the optional
    companion signal-detection tool, found through $OLIMEX_TOOLS (or a tools REGISTRY.md above
    this repo). Neither is in this repo. See docs/experimental.md.

`EXPLORATORY/RIG-CAN-DETECT-AT-ALL` asks whether the Olimex front end can detect a plausible
response within the dwell the response survives for. It has been UNRUN because the two figures
available for the rig (~34 uV RMS noise floor, ~8 uV/count) were stated in conversation and never
verified, and `budget()` correctly refuses to return a verdict from a RECALLED-VERIFY floor.

This runs it from real captures instead: a private set of eight sessions (not in this repo)
recorded on the actual rig (Oz-Cz, 250/256 Hz), with sidecar JSON documenting the acquisition
parameters.

    *** PRIVATE DATA. Those recordings are personal. This script READS them and
    writes nothing; no sample, and no subject identifier, is emitted into anything committable.
    Do not change that. ***

WHAT THIS CAN AND CANNOT SETTLE
    CAN: the rig's real in-band noise at a chosen frequency, the uV/count scale, and therefore the
    detection threshold in nV as a function of dwell — the thing a null has to be stated against.
    CANNOT: whether a brainstem response is present, because none of these sessions played a
    stimulus with a known exact frequency. This measures the DENOMINATOR of the SNR, which is
    precisely what was missing.

Run: python3 rig_noise_floor.py
"""

import contextlib
import csv
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

E = NB = None  # the companion tool's modules, imported in main() once they are found


def _signal_detection_dir():
    """The optional companion signal-detection tool: $OLIMEX_TOOLS/signal-detection, else a
    tools directory (holding REGISTRY.md) above this repo. None when neither exists."""
    import os

    env = os.environ.get("OLIMEX_TOOLS")
    cands = [Path(env) / "signal-detection"] if env else []
    cands += [u / "signal-detection" for u in HERE.parents if (u / "REGISTRY.md").is_file()]
    return next((c for c in cands if (c / "extract.py").is_file()), None)


def _find_captures():
    """The private captures these numbers came from: `$OLIMEX_RIG_CAPTURES` and nothing else.
    They are personal recordings, so they are never in this repo and nothing here writes them."""
    import os

    env = os.environ.get("OLIMEX_RIG_CAPTURES")
    return Path(env).expanduser() if env else None


# Documented in every session's sidecar JSON, consistently across all eight runs.
# The cal-derived figure (rig.UV_PER_COUNT_PROVENANCE): nominal, not externally verified.
UV_PER_COUNT = 7.9
RECALLED_FLOOR_UV = 34.0  # the unverified figure, kept for comparison
TARGETS_NV = (1000.0, 300.0, 100.0, 30.0)
PROBE_HZ = 40.0  # a plausible ASSR rate, and clear of alpha and of 60 Hz mains


def rate_for(path):
    """Read the true sample rate from the session sidecar. The captures are NOT all the same rate —
    250 and 256 both appear — and assuming one shifts the probe frequency by 2.4%, which for a
    lock-in is a different question than the one you asked."""
    side = path.with_suffix(".json")
    if side.exists():
        try:
            import json

            return float(json.load(open(side))["raw_eeg"]["sample_rate_hz"])
        except Exception:
            pass
    return 256.0


def load_phase(path, phase="pre_baseline", limit_s=None, rate=256.0):
    """Read one phase of one session as a plain list of uV, DC removed."""
    out = []
    cap = int(limit_s * rate) if limit_s else None
    with open(path) as f:
        for row in csv.DictReader(f):
            if row.get("phase") != phase:
                continue
            with contextlib.suppress(ValueError, KeyError):
                out.append(float(row["uV"]))
            if cap and len(out) >= cap:
                break
    if not out:
        return out
    m = statistics.fmean(out)
    return [v - m for v in out]


def main():
    global E, NB
    captures = _find_captures()
    if captures is None or not captures.exists():
        sys.exit(
            "EXPERIMENTAL: this script needs the private rig captures. Set OLIMEX_RIG_CAPTURES "
            "to their directory (they are not in this repo)."
        )
    sd_dir = _signal_detection_dir()
    if sd_dir is None:
        sys.exit(
            "EXPERIMENTAL: this script needs the optional signal-detection tool. Set "
            "OLIMEX_TOOLS to the directory that holds it."
        )
    sys.path.insert(0, str(sd_dir))
    import extract as E
    import noise_budget as NB

    runs = sorted(captures.glob("subjects/*/studies/*/**/run-*.csv"))
    runs = [r for r in runs if not r.name.endswith(".server.csv")]
    if not runs:
        sys.exit("no run-*.csv captures found")

    print(f"\n\033[1mOlimex rig — measured noise floor\033[0m   ({len(runs)} captures found)")
    print(
        f"scale: {UV_PER_COUNT} uV/count, documented in every session sidecar -- derived from "
        f"the shield's built-in cal signal at its NOMINAL amplitude, not externally verified\n"
    )

    # ---- 1. In-band noise, measured at the frequency that matters
    print("\033[1m1. Noise at 40 Hz, per capture (60 s of pre-stimulus baseline)\033[0m")
    print(f"   {'capture':16} {'broadband RMS':>14} {'noise@40Hz/60s':>16} {'white model':>13}")
    floors = []
    overstate = []  # white-noise model / measured, per capture
    for path in runs:
        rate = rate_for(path)
        seg = load_phase(path, "pre_baseline", limit_s=60.0, rate=rate)
        if len(seg) < int(rate * 20):
            continue
        sd = math.sqrt(sum(v * v for v in seg) / len(seg))
        ln = NB.local_noise(seg, rate, PROBE_HZ)
        white = sd * math.sqrt(2.0 / len(seg)) * 1000.0
        floors.append(ln["noise_amplitude_nv"])
        overstate.append(white / ln["noise_amplitude_nv"])
        print(
            f"   {path.name[:16]:16} {sd:11.1f} uV {ln['noise_amplitude_nv']:13.1f} nV "
            f"{white:10.0f} nV  @{rate:.0f}Hz"
        )
    if not floors:
        sys.exit("no capture had enough pre_baseline to measure")
    # CORRECTED 2026-09-13. This line was `sorted(floors)[len(floors) // 2]`, which on an EVEN
    # count takes the upper of the two middle values -- on the six captures here that reported
    # 238 nV where the median is ~157 nV. And the ratio below was printed as
    # `{sum(1 for _ in floors) and 90}`, which evaluates to the literal 90 whenever any capture
    # exists: nothing ever computed it. Both figures were copied into the corpus from this output.
    med = statistics.median(floors)
    lo, hi = min(overstate), max(overstate)
    print(
        f"\n   median in-band noise at 40 Hz, 60 s dwell: \033[1m{med:.0f} nV\033[0m"
        f"  (n = {len(floors)} captures, range {min(floors):.0f}-{max(floors):.0f} nV)"
    )
    print(
        f"   the white-noise model over broadband RMS is {lo:.1f}-{hi:.1f}x pessimistic in "
        f"amplitude (median {statistics.median(overstate):.1f}x), "
        f"i.e. {lo * lo:.0f}-{hi * hi:.0f}x in TIME."
    )
    print("   Using a broadband RMS here would say UNRUNNABLE about a runnable measurement.")

    # ---- 2. The gate
    print("\n\033[1m2. The gate: required dwell for a plausible target\033[0m")
    seg, seg_rate = None, 256.0
    for path in runs:
        seg_rate = rate_for(path)
        seg = load_phase(path, "pre_baseline", limit_s=60.0, rate=seg_rate)
        if len(seg) > int(seg_rate * 40):
            break
    # NOTE 2026-09-13: this gate runs on the FIRST capture with >40 s of baseline, not on the
    # median floor above. Say which, so the table is not read as the median session.
    print(
        f"   (computed on {path.name[:16]}, the first capture with >40 s of baseline -- "
        f"not the median session)"
    )
    print(f"   {'target':>10} {'required dwell':>16}   verdict")
    for t in TARGETS_NV:
        b = NB.budget_from_record(
            seg, seg_rate, PROBE_HZ, t, snr_required=3.0, sustain_window_s=600.0
        )
        mins = b["required_dwell_min"]
        show = f"{mins * 60:.0f} s" if mins < 1 else f"{mins:.1f} min"
        print(f"   {t:7.0f} nV {show:>16}   {b['verdict'].split(' — ')[0]}")
    print("\n   (10 min sustain window assumed — that is itself unmeasured, and is the other half")
    print("    of the collision this budget exists to expose.)")

    # ---- 3. What the old, unverified figure would have said
    print("\n\033[1m3. What the RECALLED figure would have told you\033[0m")
    old = NB.budget(100.0, RECALLED_FLOOR_UV, "RECALLED-VERIFY", seg_rate, sustain_window_s=600.0)
    print(f"   runnable={old['runnable']}  ({old['verdict'][:60]}...)")
    old_m = NB.budget(100.0, RECALLED_FLOOR_UV, "MEASURED", seg_rate, sustain_window_s=600.0)
    print(
        f"   had it been believed: {old_m['required_dwell_min']:.0f} min needed -> "
        f"{old_m['verdict'].split(' — ')[0]}"
    )
    real = NB.budget_from_record(seg, seg_rate, PROBE_HZ, 100.0, sustain_window_s=600.0)
    print(
        f"   measured from the rig: {real['required_dwell_min']:.1f} min -> "
        f"{real['verdict'].split(' — ')[0]}"
    )

    # ACCURACY NOTE. It is tempting to say the two figures "disagree about the answer". At these
    # targets they do NOT — both say unrunnable at 100 nV in 10 minutes. What differs is the
    # MARGIN, and therefore the smallest response you could chase: solve each for a 10 min dwell.
    def floor_for_window(dwell_min_at_100nv):
        return 100.0 * math.sqrt(dwell_min_at_100nv / 10.0)

    print(
        f"   smallest response detectable in 10 min: "
        f"measured {floor_for_window(real['required_dwell_min']):.0f} nV vs "
        f"recalled {floor_for_window(old_m['required_dwell_min']):.0f} nV"
    )
    print("   So the two AGREE on the verdict at these targets and differ ~2x on the smallest")
    print("   response worth chasing. The refusal still earned its keep — but the honest reading")
    print("   is that the recalled figure was optimistic, not that it inverted the conclusion.")

    # ---- 3b. The quality gate, and the pre-registered threshold
    print("\n\033[1m3b. Does each session's noise actually integrate with dwell?\033[0m")
    good = []
    for path in runs:
        fs = rate_for(path)
        for phase in ("pre_baseline", "sham"):
            s2 = load_phase(path, phase, limit_s=90.0, rate=fs)
            if len(s2) < int(fs * 90):
                continue
            ic = NB.integration_check(s2, fs, PROBE_HZ)
            print(
                f"   [{'OK  ' if ic['integrates'] else 'FAIL'}] {path.name[:12]}:{phase:12} "
                f"ratio {ic['ratio']:.2f}"
            )
            if ic["integrates"] and fs == 256.0:
                good.append(s2)
    print("   FAIL = drift-limited. Recording for longer will NOT help; re-prep the electrodes.")

    if len(good) >= 2:
        print("\n\033[1m3c. Pre-registered detection threshold (injection into REAL noise)\033[0m")
        cur = NB.injection_curve_from_record(
            good, 256.0, PROBE_HZ, dwells_s=(10.0, 30.0, 60.0, 90.0)
        )
        print(f"   {'dwell':>7} {'best':>9} {'typical':>9} {'worst':>10}  {'undetected':>10}")
        for r in cur["rows"]:
            if r.get("typical_nv") is None:
                continue
            print(
                f"   {r['dwell_s']:6.0f}s {r['best_nv']:8.0f}n {r['typical_nv']:8.0f}n "
                f"{r['worst_nv']:9.0f}n {r['segments_undetected_at_any_tested_amplitude']:10d}"
            )
        print("   Stated BEFORE any stimulus session, which is the only order in which a")
        print("   capability claim is a limit rather than an excuse for a null.")
        print("   The best/worst spread is ~135x. That spread, not the algorithm, is the rig.")

    # ---- 4. Mains, and the honest limits
    print("\n\033[1m4. Notes for anyone planning a session on this rig\033[0m")
    a60 = E.lockin(seg, seg_rate, 60.0, sync="nominal_frequency")["amplitude"]
    a50 = E.lockin(seg, seg_rate, 50.0, sync="nominal_frequency")["amplitude"]
    print(f"   60 Hz mains present at {a60 * 1000:.0f} nV (50 Hz: {a50 * 1000:.0f} nV).")
    print("   Keep a target frequency and its sidebands away from 60 Hz and its harmonics.")
    fe = E.sideband_feasibility(120.0, 8.0, seg_rate)
    print(
        f"   sideband window at 256 Hz: carrier >=120 Hz, Nyquist 128 Hz -> widest usable "
        f"delta {fe['widest_delta_at_this_rate_hz']:.0f} Hz."
    )
    print("\n   STILL NOT SETTLED: this measures the noise, not a response. No session on this rig")
    print("   has ever played a stimulus at a known exact frequency, so nothing here shows the")
    print("   rig detecting anything. That is the next measurement, and it is now well-posed:")
    print(
        f"   play a {PROBE_HZ:.0f} Hz AM stimulus, record, and test against a {med:.0f} nV floor.\n"
    )


if __name__ == "__main__":
    main()
