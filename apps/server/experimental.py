"""experimental.py -- every EXPERIMENTAL route and figure the bridge serves, in one place.

Nothing here is an established method for this hardware (a 10-bit, single-channel hobby
amplifier whose microvolt scale is not externally verified). See docs/experimental.md.

What lives here:

  * the routes backed by the OPTIONAL companion analysis tools -- lock-in extraction, the
    integration check, the noise budget, detection curves, the rate trade, and the auditory
    atlas (`/predict`, `/montage`, `/simulate`, `/atlas/reference`, `/claims`). The tools are
    found through `$OLIMEX_TOOLS` (or by walking up to a directory holding a tools
    `REGISTRY.md`); without them every route here answers 503 "not installed";
  * this rig's nV noise figures and the RECALLED table, which only those routes use.

Every response from here carries `"experimental": true` and a short `"note"`, including the
503s, so a client can never render one of these numbers as if it were core.

THE DEPENDENCY RUNS ONE WAY. `serve.py` imports this module inside a guard; nothing in the
acquisition path (`SerialDaemon`, `quality`, `timebase`, `durability`, `sessions`) imports it.
Acquisition is the job that is not allowed to fail, and an analysis tool that fails to import
must not be able to take a serial port down mid-session.
"""

import importlib.util as _ilu
import os
import sys

NOTE = (
    "Experimental: not an established method for this hardware; see docs/experimental.md. "
    "Microvolt and nanovolt figures inherit the rig's uV/count scale, which is not externally "
    "verified."
)

DEFAULT_RATE = 250


def mark(obj):
    """Stamp a response as experimental. A non-dict result is wrapped under `result`."""
    if not isinstance(obj, dict):
        obj = {"result": obj}
    out = dict(obj)
    out["experimental"] = True
    out.setdefault("note", NOTE)
    if out["note"] != NOTE:
        out["experimental_note"] = NOTE
    return out


# ------------------------------------------------------------------ this rig's figures (EXP) --
# These depend on the unverified uV/count scale (rig.UV_PER_COUNT_PROVENANCE) and on private
# captures that are not in this repo, and they are only consumed by the experimental routes.

#: Stated in voice, NEVER verified against the Olimex SHIELD-EKG-EMG datasheet or the Arduino ADC
#: specification. Present so the unknown is explicit and callable; tagged so it cannot be used as if
#: it were measured. Re-derive before either number appears in anything.
RECALLED = {
    "noise_floor_uv_rms": 34.0,
    "uv_per_count": 8.0,
    "provenance": "RECALLED-VERIFY",
    "corpus_eligible": False,
    "experimental": True,
    "how_to_verify": "Short the inputs through a resistor matching realistic electrode-skin "
    "impedance, record for several minutes with the acquisition service, and take "
    "the RMS in the target band. Datasheet second, measured first — the datasheet "
    "figure is not this rig's figure at this impedance.",
}

#: In-band noise at 40 Hz over a 60 s dwell, from six private captures
#: (validation/VALIDATION.md). EXPERIMENTAL; the 11.7x spread is NOT attributed.
NOISE_NV_AT_40HZ = {
    "median": 156.7,
    "min": 64.3,
    "max": 750.2,
    "experimental": True,
}  # corrected 2026-09-13; was 238/65/750

#: Computed on ONE capture (the first with >40 s of baseline, the 750 nV one), not on the median.
SMALLEST_DETECTABLE_NV_IN_10MIN = 712.0

# Measured 2026-08-17 from this rig's own private captures (not in this repo; 6 usable sessions,
# Oz-Cz, 250/256 Hz) by validation/rig_noise_floor.py. Aggregate statistics; no subject data.
MEASURED_RIG = {
    "uv_per_count": 7.9,
    "uv_per_count_provenance": "the 7.9 documented in all 8 session sidecars, which came from "
    "the shield's built-in cal signal at its nominal amplitude; consistent, but not an "
    "independent or external verification.",
    # The number that actually governs detection. A broadband RMS is NOT this number: real EEG is
    # drift-dominated, and on these captures the broadband figure over-estimated the noise at 40 Hz
    # by 3.5-24x in amplitude (median ~15x). Quote this one, and quote it WITH its dwell.
    # CORRECTED 2026-09-13: this block said median 238 nV and 20-90x. 238 was the upper-middle of
    # six values (rig_noise_floor.py indexed sorted()[n//2]) and "90" was a hard-coded literal in
    # that script's print. Recomputed from the same six captures.
    "in_band_noise_nv_at_40hz_60s": NOISE_NV_AT_40HZ["median"],
    "in_band_noise_nv_range": (NOISE_NV_AT_40HZ["min"], NOISE_NV_AT_40HZ["max"]),
    "in_band_noise_provenance": "median across 6 sessions of 60 s pre-stimulus baseline, via "
    "neighbouring-bin estimation at 40 Hz; scaled by the unverified uV/count.",
    "smallest_detectable_nv_in_10min": SMALLEST_DETECTABLE_NV_IN_10MIN,
    "mains_hz": 60.0,
    "note": "The 11.7x spread across sessions (64-750 nV) is larger than any algorithmic factor in "
    "this tool. It was previously attributed to electrode preparation; the sidecars do not "
    "support that attribution. The one capture scored good-contact (alpha SNR 36) has the "
    "HIGHEST 40 Hz figure, and the one flagged as implausibly small sits mid-range, so this is "
    "in-band power of a scalp recording (EEG and scalp EMG included), not instrument noise. "
    "No shorted-input measurement has been made. CORRECTED 2026-09-13.",
    "corpus_eligible": True,
    "experimental": True,
}


# ------------------------------------------------------------------- optional analysis tools --


def _tools_dir():
    env = os.environ.get("OLIMEX_TOOLS")
    if env:
        return env if os.path.isdir(env) else None
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        here = os.path.dirname(here)
        if os.path.isfile(os.path.join(here, "REGISTRY.md")):
            return here
    return None


TOOLS_DIR = _tools_dir()


def _tool_path(name):
    return os.path.join(TOOLS_DIR, name) if TOOLS_DIR else None


def _load_by_path(alias, path):
    spec = _ilu.spec_from_file_location(alias, path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Missing:
    """Stands in for a tool that is not installed, so an `except x.DomainError` clause can never
    itself NameError while handling an error -- the worst failure mode for the acquisition
    service."""

    class DomainError(ValueError):
        pass

    class ModalityError(TypeError):
        pass


def _missing(what, err):
    return mark(
        {
            "error": f"{what} is not installed here",
            "detail": err,
            "hint": (
                "these routes come from the optional companion analysis tools "
                "(auditory-atlas, signal-detection); set OLIMEX_TOOLS to the directory "
                "that holds them"
            ),
        }
    )


try:
    if not TOOLS_DIR:
        raise ImportError("no companion tools directory found (OLIMEX_TOOLS unset)")
    sys.path.insert(0, _tool_path("auditory-atlas"))
    import auditory
    import electrodes
    import forward
    import montage

    atlas_claims = _load_by_path(
        "atlas_claims", os.path.join(_tool_path("auditory-atlas"), "claims.py")
    )
    _HAVE_ATLAS, _ATLAS_ERROR = True, None
except Exception as _e:  # pragma: no cover - import guard
    _HAVE_ATLAS, _ATLAS_ERROR = False, str(_e)
    auditory = _Missing()
    atlas_claims = None

try:
    if not TOOLS_DIR:
        raise ImportError("no companion tools directory found (OLIMEX_TOOLS unset)")
    sys.path.insert(0, _tool_path("signal-detection"))
    import extract
    import noise_budget

    detection_claims = _load_by_path(
        "detection_claims", os.path.join(_tool_path("signal-detection"), "claims.py")
    )
    _HAVE_DETECTION, _DETECTION_ERROR = True, None
except Exception as _e:  # pragma: no cover - import guard
    _HAVE_DETECTION, _DETECTION_ERROR = False, str(_e)
    extract = _Missing()
    detection_claims = None

FIREWALL_ERRORS = tuple(
    {
        getattr(m, n)
        for m in (auditory, extract)
        for n in ("DomainError", "ModalityError")
        if hasattr(m, n)
    }
)


def _tone():
    """injrec.tone, loaded by path: the injrec package imports numpy, this module does not."""
    return _load_by_path(
        "injrec_tone", os.path.join(_tool_path("injection-recovery"), "injrec", "tone.py")
    )


def all_claims():
    """The registers of every analysis tool that is present, as one four-register document."""
    regs = [c for c in (atlas_claims, detection_claims) if c is not None]
    out = {
        k: [e for c in regs for e in getattr(c, k.upper())]
        for k in ("evidence", "refuted", "exploratory", "mythos")
    }
    out["counts"] = {k: len(v) for k, v in out.items()}
    out["counts"]["evidence_by_tier"] = {
        t: sum(1 for e in out["evidence"] if e["tier"] == t) for t in ("A", "B", "C")
    }
    out["sources"] = [c.__name__ for c in regs]
    return out


def atlas_reference():
    """Everything static a client needs to render an atlas answer, in one cacheable request."""
    return {
        "protocol": montage.PROTOCOL_VERSION,
        "electrodes": electrodes.positions(),
        "set1020": electrodes.SET_1020,
        "capTiers": [
            {"electrodes": c, "tier": tier, "means": m} for c, tier, m in electrodes.CAP_TIERS
        ],
        "sphereInvalid": sorted(electrodes.SPHERE_INVALID),
        "generators": {
            k: {
                "label": v["label"],
                "mni": list(v["mni"]),
                "orient": list(v["orient"]),
                "ceilingHz": v["ceiling_hz"],
                "depth": v["depth"],
                "modality": v.get("modality", "acoustic"),
                "note": v.get("note", ""),
            }
            for k, v in auditory.GENERATORS.items()
        },
        "responses": [
            {
                "id": r["id"],
                "label": r["label"],
                "tier": r["tier"],
                "family": r["family"],
                "modality": r["modality"],
                "latencyMs": list(r["latency_ms"]),
                "typicalUv": r["typical_uv"],
                "follows": r["follows"],
                "polarity": r["polarity"],
                "reading": r["reading"],
                "cite": r["cite"],
                "generators": [
                    {"id": g, "weight": w, "rule": rule} for g, w, rule in r["generators"]
                ],
            }
            for r in auditory.RESPONSES
        ],
        "transducers": {
            k: {kk: vv for kk, vv in v.items()} for k, v in auditory.TRANSDUCERS.items()
        },
        "hapticSites": auditory.HAPTIC_SITES,
        "tactileChannels": [
            {"name": n, "loHz": lo, "hiHz": hi, "note": note}
            for n, lo, hi, note in auditory.TACTILE_CHANNELS
        ],
        "domains": {
            "rateMaxHz": auditory.RATE_MAX_HZ,
            "carrierMinHz": auditory.CARRIER_MIN_HZ,
            "itdCeilingUs": auditory.ITD_CEILING_US,
        },
        "specificity": montage.SPECIFICITY,
        "smearRad": forward.SMEAR_RAD,
        "claims": all_claims(),
    }


def extract_reference():
    """What a client needs to call the extraction endpoints correctly, including the two rig
    figures that are RECALLED-VERIFY rather than measured."""
    return {
        "syncSources": extract.SYNC_SOURCES,
        "hardwareControls": extract.HARDWARE_CONTROLS,
        "artifactLatencyFloorMs": extract.ARTIFACT_LATENCY_MS,
        "provenance": noise_budget.PROVENANCE,
        "verdictTiers": sorted(noise_budget.VERDICT_TIERS),
        "recalledRigFigures": RECALLED,
    }


def _refs_for(body):
    """Reference frequencies. Either an explicit list, or a carrier + modulation depth, in which
    case the sideband firewall builds the three correct references and refuses the swap."""
    if body.get("carrier_hz") is not None and body.get("delta_hz") is not None:
        # Check Nyquist BEFORE building references, so the caller gets the acquisition-rate answer
        # ("record faster") rather than a bare alias complaint about one frequency.
        fe = extract.sideband_feasibility(
            float(body["carrier_hz"]),
            float(body["delta_hz"]),
            float(body.get("rate", DEFAULT_RATE)),
        )
        if not fe["feasible"]:
            raise ValueError(fe["reading"] + " " + fe["rig_note"])
        return extract.sideband_refs(float(body["carrier_hz"]), float(body["delta_hz"]))
    refs = body.get("refs") or ([body["ref_hz"]] if body.get("ref_hz") is not None else [])
    if not refs:
        raise ValueError("no references: pass `ref_hz`, `refs`, or `carrier_hz` + `delta_hz`")
    return [r if isinstance(r, dict) else {"hz": float(r), "role": None} for r in refs]


def _opt(body, key):
    return None if body.get(key) is None else float(body[key])


# ------------------------------------------------------------------------------- routes --

GET_ROUTES = ("/claims", "/atlas/reference", "/extract/reference")
ATLAS_POST = ("/predict", "/montage", "/simulate")
DETECTION_POST = (
    "/integration-check",
    "/extract",
    "/extract/sustain",
    "/extract/artifact",
    "/extract/feasibility",
    "/noise-budget",
    "/detection-curve",
    "/rate-trade",
)
ROUTES = GET_ROUTES + tuple("POST " + p for p in ATLAS_POST + DETECTION_POST)


def is_route(path):
    """True for any path this module serves (so its errors can be marked experimental too)."""
    return (
        path in GET_ROUTES
        or path in ATLAS_POST
        or path in DETECTION_POST
        or (path.startswith("/extract"))
    )


def handle_get(path):
    """(status, body) for an experimental GET route, or None if `path` is not one."""
    if path == "/claims":
        if not (_HAVE_ATLAS or _HAVE_DETECTION):
            return 503, _missing("the atlas and signal-detection", _ATLAS_ERROR)
        return 200, mark(all_claims())
    if path == "/atlas/reference":
        if not _HAVE_ATLAS:
            return 503, _missing("the auditory atlas", _ATLAS_ERROR)
        return 200, mark(atlas_reference())
    if path == "/extract/reference":
        if not _HAVE_DETECTION:
            return 503, _missing("signal-detection", _DETECTION_ERROR)
        return 200, mark(extract_reference())
    return None


def handle_post(path, body, *, samples_for, rate_for):
    """(status, body) for an experimental POST route, or None if `path` is not one.

    `samples_for(body)` and `rate_for(body)` are the bridge's own helpers (supplied samples, or
    the tail of the daemon's ring, and the rate with its basis). This module never reaches into
    the daemon itself. Exceptions propagate to the bridge's handler, which maps them to 400/500.
    """
    if path in ATLAS_POST:
        if not _HAVE_ATLAS:
            return 503, _missing("the auditory atlas", _ATLAS_ERROR)
        return 200, mark(_atlas_post(path, body))
    if path in DETECTION_POST or path.startswith("/extract"):
        if not _HAVE_DETECTION:
            return 503, _missing("signal-detection", _DETECTION_ERROR)
        out = _detection_post(path, body, samples_for, rate_for)
        if out is None:
            return 404, mark({"error": "not found"})
        return 200, mark(out)
    return None


def _atlas_post(path, body):
    stim = body.get("stimulus", body)
    if path == "/predict":
        # The scalp field rides along: the UI needs it for every response.
        return forward.attach_topography(auditory.predict(stim))
    if path == "/montage":
        return montage.recommend(
            stim,
            channels=body.get("channels", "cap"),
            goal=body.get("goal", "auto"),
            electrode_type=body.get("electrode_type", "cup"),
        )
    pred = auditory.predict(stim)
    sites = body.get("sites") or ["Cz", "Fz", "C3", "C4", "M1", "M2", "T7", "T8"]
    return forward.synth(
        pred,
        sites,
        seconds=float(body.get("seconds", 4.0)),
        rate=float(body.get("rate", DEFAULT_RATE)),
        seed=int(body.get("seed", 1)),
        mains_hz=float(body.get("mains_hz", 60.0)),
        impedance_imbalance=float(body.get("impedance_imbalance", 0.25)),
        show_noise=bool(body.get("show_noise", True)),
        event_rate_hz=float(body.get("event_rate_hz", 1.0)),
    )


def _detection_post(path, body, samples_for, rate_for):
    if path == "/integration-check":
        rate, _basis = rate_for(body)
        samples = samples_for(body)
        return noise_budget.integration_check(samples, rate, float(body.get("ref_hz", 40.0)))
    if path == "/extract/feasibility":
        return extract.sideband_feasibility(
            float(body["carrier_hz"]),
            float(body["delta_hz"]),
            float(body.get("rate", DEFAULT_RATE)),
        )
    if path == "/rate-trade":
        return extract.rate_trade(
            [(r[0], r[1]) for r in body.get("amplitude_by_rate", [])],
            minutes=float(body.get("minutes", 1.0)),
            sustain_floor=_opt(body, "sustain_floor"),
        )
    if path == "/noise-budget":
        return noise_budget.budget(
            float(body["target_nv"]),
            float(body["noise_floor_uv_rms"]),
            body.get("provenance", "RECALLED-VERIFY"),
            rate_hz=float(body.get("rate", DEFAULT_RATE)),
            snr_required=float(body.get("snr_required", 3.0)),
            sustain_window_s=_opt(body, "sustain_window_s"),
            uv_per_count=_opt(body, "uv_per_count"),
        )
    if path == "/detection-curve":
        return _tone().detection_curve(
            float(body["noise_floor_uv_rms"]),
            body.get("provenance", "RECALLED-VERIFY"),
            rate_hz=float(body.get("rate", DEFAULT_RATE)),
            ref_hz=float(body.get("ref_hz", 40.0)),
            dwells_s=tuple(body.get("dwells_s", (1.0, 4.0, 16.0))),
            trials=int(body.get("trials", 8)),
            alpha=float(body.get("alpha", 0.01)),
            uv_per_count=_opt(body, "uv_per_count"),
            dither_probe=bool(body.get("dither_probe", False)),
        )

    rate, rate_basis = rate_for(body)
    sync = body.get("sync", "undeclared")
    samples = samples_for(body)
    refs = _refs_for(body)

    if path == "/extract/sustain":
        return extract.envelope_decay(
            samples,
            rate,
            refs[0]["hz"],
            window_s=float(body.get("window_s", 1.0)),
            hop_s=_opt(body, "hop_s"),
            sync=sync,
        )
    bank = extract.lockin_bank(samples, rate, refs, sync=sync)
    if path == "/extract/artifact":
        return extract.artifact_verdict(bank, controls_run=body.get("controls_run", []), sync=sync)
    if path != "/extract":
        return None
    epochs = body.get("epochs")
    out = {
        "rate": rate,
        "rate_basis": rate_basis,
        "sync": sync,
        "dwell_s": len(samples) / rate,
        "bank": bank,
        "presence": [
            extract.present(
                samples,
                rate,
                r["hz"],
                epochs=epochs,
                alpha=float(body.get("alpha", 0.01)),
                sync=sync,
            )
            for r in refs
        ],
        # PREDICTED never looks like MEASURED: this half of the tool only ever returns
        # MEASURED-family tiers, and says so rather than leaving it implied.
        "tier": bank[0]["tier"],
        "not_amplification": "These numbers describe extraction efficiency. See "
        "REFUTED/EXTRACTION-IS-NOT-AMPLIFICATION.",
    }
    if body.get("harmonic_purity_of") is not None:
        out["harmonic_purity"] = extract.harmonic_purity(
            samples, rate, float(body["harmonic_purity_of"]), sync=sync
        )
    if epochs:
        out["average"] = extract.coherent_average(epochs)
    if len(bank) > 1:
        out["artifact"] = extract.artifact_verdict(
            bank, controls_run=body.get("controls_run", []), sync=sync
        )
    return out
