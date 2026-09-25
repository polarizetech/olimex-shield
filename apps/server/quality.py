#!/usr/bin/env python3
"""
quality.py — is what this channel delivers PLAUSIBLE for the readout, and is it worth a session?

WHAT IT MEASURES, AND WHAT IT DOES NOT
    A signal-PLAUSIBILITY heuristic over a few seconds of samples: amplitude, rail saturation,
    the share of power at mains, and (for EEG only, and experimental) an alpha-band ratio. It does
    NOT measure electrode impedance -- nothing on this board can -- so its messages say what was
    actually measured ("flat/implausible signal -- check contact"), never "high impedance".

READOUT-AWARE
    `readout="eeg"` keeps the scalp-EEG checks (the amplitude floor and the alpha ratio). ECG, EMG
    and anything else get only conservative, physiology-free checks: rails, mains share and a
    flat-line / too-low-variance floor. Alpha is a cortical rhythm; judging a limb lead on it, or
    on a scalp-EEG amplitude floor, is a category error.

WHY THIS IS SERVER-SIDE AND WHY IT LIVES HERE
    The logic is ported from an earlier internal project, where it was right but trapped inside
    one browser app, so nothing else could ask "is this channel usable" without copying it. Here
    it is stdlib Python beside the process that owns the port, so the workbench UI, a CLI, another
    app and dev_check.py all get the same answer.

THE FINDING IT ENCODES
    A channel sitting near its own floor is measuring the room, and it will happily produce a
    plausible-looking trace and an empty result minutes later. This catches the obvious cases in
    ~20 seconds, with numbers that say which check failed.

WINDOWING
    Band estimates use a Hann window over the (mean-removed) record, then sum the power of the
    exact DFT bins whose frequency lies in [lo, hi) -- half-open, so adjacent bands (8-13, 13-30)
    never count the same bin twice and the classic bands partition 1-45 Hz exactly.

Stdlib only. Pure functions — samples in, verdict out. No device, no writes.
"""

import math

import rig


class DomainError(ValueError):
    """An input outside the domain where a measure means anything."""


def _goertzel_power(samples, rate_hz, bin_index, n):
    """Power at an exact DFT bin, without an FFT (O(n) per bin, no padding).

    A copy of `extract._goertzel_power` (the optional signal-detection tool), kept so this board's
    contact check never depends on an optional tool. The bridge's gate pins the two equal.
    """
    w = 2.0 * math.pi * bin_index / n
    coeff = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + coeff * s1 - s2
        s2, s1 = s1, s0
    real = s1 - s2 * math.cos(w)
    imag = s2 * math.sin(w)
    return real * real + imag * imag


# Ported from the original PREFLIGHT block. Amplitudes are uV of the raw standard deviation, and
# every uV figure inherits rig.UV_PER_COUNT's unverified scale.
PREFLIGHT = {
    "check_s": 20.0,  # the pre-flight window, before committing to a long baseline
    "min_amplitude_uv": 100.0,  # scalp EEG only: below this the signal is implausibly small
    "good_amplitude_uv": 150.0,
    "max_amplitude_uv": 3000.0,  # above this: railing, movement, gross drift
    "min_alpha_snr": 2.0,  # EXPERIMENTAL, EEG only
    "good_alpha_snr": 8.0,
    "mains_max_rel": 0.4,  # mains above this fraction of 2-40 Hz power: likely pickup
    "rail_max_frac": 0.02,
    "rail_frac": 0.98,  # "near rail" = within (1 - this) of either end of the ADC range
    "flat_max_counts": 1.5,  # SD at or below this many ADC counts is at the converter's floor
    "flat_max_uv": 5.0,  # ...the same floor when the samples are already in uV
}

#: Non-EEG readouts: no scalp amplitude floor, no alpha, no upper amplitude limit (an R wave or a
#: strong contraction is legitimately large; the rail check catches saturation). Only the
#: physiology-free checks remain.
PLAUSIBILITY_ONLY = {
    "min_amplitude_uv": None,
    "good_amplitude_uv": None,
    "max_amplitude_uv": None,
    "min_alpha_snr": None,
    "good_alpha_snr": None,
}

METHOD = "plausibility heuristic"

CHECKLISTS = {
    "eeg": [
        "Re-gel the electrodes; part the hair so metal touches scalp, not hair.",
        "Check the cable and shield jumper seating.",
        "Check the REFERENCE and GROUND, not just the active electrode.",
        "Reduce mains: unplug chargers, move away from monitors and power bricks.",
        "Watch the amplitude number change as contact improves.",
    ],
    "other": [
        "Check that each electrode is seated on clean skin and its lead is clipped on.",
        "Check the cable and shield jumper seating.",
        "Check the REFERENCE and GROUND, not just the active electrode.",
        "Reduce mains: unplug chargers, move away from monitors and power bricks.",
    ],
}
#: Kept for callers that imported the EEG list by its old name.
CHECKLIST = CHECKLISTS["eeg"]


def _bin_range(n, rate_hz, lo_hz, hi_hz):
    """Inclusive bins whose frequency k*rate/n lies in [lo_hz, hi_hz), clipped to (0, n/2)."""
    k_lo = max(1, int(math.ceil(lo_hz * n / rate_hz - 1e-9)))
    k_hi = min(n // 2 - 1, int(math.ceil(hi_hz * n / rate_hz - 1e-9)) - 1)
    return k_lo, k_hi


def _hann(x):
    n = len(x)
    if n < 2:
        return list(x)
    return [v * (0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))) for i, v in enumerate(x)]


def _prepared(samples, window):
    n = len(samples)
    mean = sum(samples) / n
    x = [v - mean for v in samples]
    return _hann(x) if window == "hann" else x


def band_power(samples, rate_hz, lo_hz, hi_hz, window="hann", _prepared_x=None):
    """Summed power of the DFT bins in [lo_hz, hi_hz), by Goertzel, after a Hann window.

    Deliberately NOT a Welch PSD: this service is stdlib-only and already owns an exact single-bin
    estimator. For a band ratio -- which is all any threshold here uses -- summed bin power is the
    same quantity up to a normalisation that cancels. `window="rect"` gives the old unwindowed sum.
    """
    n = len(samples)
    if n < 32:
        raise DomainError("need at least 32 samples for a band power")
    rate_hz = float(rate_hz)
    if lo_hz >= hi_hz:
        raise DomainError("band low edge must be below the high edge")
    x = _prepared_x if _prepared_x is not None else _prepared(samples, window)
    k_lo, k_hi = _bin_range(n, rate_hz, lo_hz, hi_hz)
    if k_hi < k_lo:
        return 0.0
    return sum(_goertzel_power(x, rate_hz, k, n) for k in range(k_lo, k_hi + 1))


def _mains_hz(mains_hz):
    """(Hz, basis). A caller's value wins, then $OLIMEX_MAINS_HZ, then the bench default."""
    if mains_hz is not None:
        return float(mains_hz), "caller"
    env = rig.configured_mains_hz()
    if env is not None:
        return env, rig.MAINS_ENV
    return rig.MAINS_HZ, "bench default (rig.MAINS_HZ); set OLIMEX_MAINS_HZ for another grid"


def assess(
    samples,
    rate_hz,
    uv_per_count=1.0,
    adc_max=1023.0,
    mains_hz=None,
    already_uv=False,
    cfg=None,
    readout="eeg",
):
    """The pre-flight verdict. `level` is one of good / marginal / unusable / no_signal.

    `level` grades PLAUSIBILITY for the readout, not impedance and not what a session will find.
    `readout` picks the checks: "eeg" (default) keeps the scalp amplitude floor and the
    experimental alpha ratio; anything else ("ecg", "emg", ...) gets rails, mains share and a
    flat-line floor only.

    `samples` may be raw ADC counts (default) or already in uV (`already_uv=True`) -- the daemon
    serves counts, older CSVs store uV, and guessing between them silently would put the
    amplitude thresholds out by a factor of ~8.
    """
    readout = str(readout or "eeg").lower()
    is_eeg = readout == "eeg"
    c = dict(PREFLIGHT)
    if not is_eeg:
        c.update(PLAUSIBILITY_ONLY)
    if cfg:
        c.update({k: v for k, v in cfg.items() if k != "readout"})
    mains_hz, mains_basis = _mains_hz(mains_hz)
    rate_hz = float(rate_hz)
    n = len(samples)
    checklist = CHECKLISTS["eeg" if is_eeg else "other"]
    base = {
        "method": METHOD,
        "readout": readout,
        "mains_hz": mains_hz,
        "mains_hz_basis": mains_basis,
        "thresholds": c,
    }
    if n < int(rate_hz):
        return {
            **base,
            "ready": False,
            "level": "no_signal",
            "amplitude_uv": None,
            "alpha_snr": None,
            "alpha_snr_detail": _alpha_detail(None, is_eeg, c),
            "mains_rel": None,
            "railing_frac": None,
            "flat": None,
            "seconds": n / rate_hz if rate_hz else 0,
            "reasons": ["waiting for signal — need at least one second"],
            "checklist": [],
        }

    mean = sum(samples) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in samples) / n)
    amplitude_uv = sd if already_uv else sd * float(uv_per_count)
    flat = sd <= (c["flat_max_uv"] if already_uv else c["flat_max_counts"])

    # Railing. Only meaningful on raw counts; on uV the ADC range is not recoverable.
    railing_frac = None
    if not already_uv:
        hi = adc_max * c["rail_frac"]
        lo = adc_max * (1.0 - c["rail_frac"])
        railing_frac = sum(1 for v in samples if v >= hi or v <= lo) / n

    alpha_snr = mains_rel = None
    try:
        x = _prepared(samples, "hann")
        total = band_power(samples, rate_hz, 2.0, 40.0, _prepared_x=x) or 1e-12
        mains_rel = (
            band_power(samples, rate_hz, mains_hz - 1.5, mains_hz + 1.5, _prepared_x=x) / total
        )
        if is_eeg and c.get("min_alpha_snr") is not None:
            alpha = band_power(samples, rate_hz, 8.0, 13.0, _prepared_x=x)
            floor = band_power(samples, rate_hz, 30.0, 40.0, _prepared_x=x) or 1e-12
            alpha_snr = alpha / floor
    except DomainError:
        pass

    reasons = []
    if flat:
        reasons.append(
            f"standard deviation {sd:.2f} {'uV' if already_uv else 'counts'} is at the "
            "converter's floor — flat/implausible signal: check contact and leads"
        )
    elif c.get("min_amplitude_uv") is not None and amplitude_uv < c["min_amplitude_uv"]:
        reasons.append(
            f"amplitude {amplitude_uv:.1f} uV is below the {c['min_amplitude_uv']:.0f} uV "
            "plausibility floor for scalp EEG — implausibly small signal: check contact"
        )
    if c.get("max_amplitude_uv") is not None and amplitude_uv > c["max_amplitude_uv"]:
        reasons.append(
            f"amplitude {amplitude_uv:.0f} uV is very high (> {c['max_amplitude_uv']:.0f}) — "
            "railing, movement or gross drift"
        )
    if alpha_snr is not None and alpha_snr < c["min_alpha_snr"]:
        reasons.append(
            f"alpha ratio {alpha_snr:.2f} < {c['min_alpha_snr']:g} (experimental) — no 8-13 Hz "
            "excess over 30-40 Hz (eyes closed should raise this)"
        )
    if mains_rel is not None and mains_rel > c["mains_max_rel"]:
        reasons.append(
            f"mains ({mains_hz:.0f} Hz) is {mains_rel * 100:.0f}% of 2-40 Hz power — likely "
            "mains pickup: check contact, leads and nearby mains sources"
        )
    if railing_frac is not None and railing_frac > c["rail_max_frac"]:
        reasons.append(f"{railing_frac * 100:.0f}% of samples are at the ADC rails (saturated)")

    ready = not reasons
    if not ready:
        level = "unusable"
    elif is_eeg:
        good_amp = c.get("good_amplitude_uv")
        good_alpha = c.get("good_alpha_snr")
        level = (
            "good"
            if (good_amp is None or amplitude_uv >= good_amp)
            and (alpha_snr is None or good_alpha is None or alpha_snr >= good_alpha)
            else "marginal"
        )
    else:
        # Non-EEG: "good" only with margin on every physiology-free check.
        level = (
            "good"
            if (mains_rel is None or mains_rel <= c["mains_max_rel"] / 2.0)
            and (railing_frac is None or railing_frac == 0.0)
            else "marginal"
        )

    return {
        **base,
        "ready": ready,
        "level": level,
        "amplitude_uv": amplitude_uv,
        "alpha_snr": alpha_snr,
        "alpha_snr_detail": _alpha_detail(alpha_snr, is_eeg, c),
        "mains_rel": mains_rel,
        "railing_frac": railing_frac,
        "flat": flat,
        "seconds": n / rate_hz,
        "reasons": reasons,
        "checklist": [] if ready else list(checklist),
        "note": "A signal-PLAUSIBILITY heuristic, not an impedance measurement and not a "
        "measurement of anything physiological. 'good' means the channel passed these checks "
        "for this readout — it says nothing about what the session will find. Microvolt "
        "figures inherit rig.UV_PER_COUNT, which is not externally verified.",
    }


def _alpha_detail(value, is_eeg, c):
    return {
        "value": value,
        "applied": bool(is_eeg and c.get("min_alpha_snr") is not None),
        "experimental": True,
        "band_hz": [8.0, 13.0],
        "floor_hz": [30.0, 40.0],
        "note": "EXPERIMENTAL: summed Hann-windowed bin power 8-13 Hz over 30-40 Hz. A heuristic "
        "for scalp EEG only; not applied to other readouts.",
    }


def bands(samples, rate_hz):
    """Classic band powers, as relative fractions of 1-45 Hz. For the scope's readout.

    Bands are half-open [lo, hi) over exact DFT bins after a Hann window, so they partition
    1-45 Hz and the fractions sum to 1.

    Returned as FRACTIONS on purpose. An absolute band power in bin-sum units is a number nobody can
    interpret and everybody will quote; a fraction is at least honest about being a ratio. See the
    bridge's standing honesty note: band power is a noisy, artefact-prone proxy and jaw clench moves
    'alpha' convincingly.
    """
    edges = [
        ("delta", 1.0, 4.0),
        ("theta", 4.0, 8.0),
        ("alpha", 8.0, 13.0),
        ("beta", 13.0, 30.0),
        ("gamma", 30.0, 45.0),
    ]
    if len(samples) < 32:
        raise DomainError("need at least 32 samples for a band power")
    x = _prepared(samples, "hann")
    total = band_power(samples, rate_hz, 1.0, 45.0, _prepared_x=x) or 1e-12
    out = {
        name: band_power(samples, rate_hz, lo, hi, _prepared_x=x) / total for name, lo, hi in edges
    }
    out["_caveat"] = (
        "Fractions of 1-45 Hz power (Hann window, half-open bands). Band power is a proxy: "
        "blinks, jaw clench and neck tension move these convincingly. Not evidence of a state."
    )
    return out


def spectrum(samples, rate_hz, lo_hz=1.0, hi_hz=45.0, bins=120):
    """A coarse amplitude spectrum for drawing. Averages Goertzel bins into `bins` display buckets,
    so the cost is bounded by the display width rather than by the record length."""
    n = len(samples)
    rate_hz = float(rate_hz)
    if n < 64:
        raise DomainError("need at least 64 samples for a spectrum")
    x = _prepared(samples, "hann")
    # Hann coherent gain is 0.5, so a sinusoid's amplitude is 2*sqrt(p) / (0.5 * n).
    norm = 0.5 * n
    k_lo = max(1, int(lo_hz * n / rate_hz))
    k_hi = min(n // 2 - 1, int(hi_hz * n / rate_hz))
    if k_hi <= k_lo:
        return {"freqs": [], "amps": []}
    step = max(1, (k_hi - k_lo) // bins)
    freqs, amps = [], []
    for k in range(k_lo, k_hi + 1, step):
        p = _goertzel_power(x, rate_hz, k, n)
        freqs.append(k * rate_hz / n)
        amps.append(2.0 * math.sqrt(p) / norm)
    return {"freqs": freqs, "amps": amps, "resolution_hz": rate_hz / n, "window": "hann"}
