"""The routes behind `olimex_shield_ext_experimental`: every EXPERIMENTAL route and figure.

Nothing here is an established method for this hardware (a 10-bit, single-channel hobby
amplifier whose microvolt scale is not externally verified). See docs/experimental.md.

What lives here:

  * the routes backed by the OPTIONAL companion analysis tools -- lock-in extraction, the
    integration check, the noise budget, detection curves, the rate trade, and the auditory
    atlas (`/predict`, `/montage`, `/simulate`, `/atlas/reference`, `/claims`). The tools are
    found through `$OLIMEX_TOOLS` (or by walking up to a directory holding a tools
    `REGISTRY.md`); without them every route here answers 503 "not installed";
  * the optional RIG PROFILE: a board's noise floor (and optionally its scale), supplied by the
    user as a JSON file named by `$OLIMEX_RIG_PROFILE`. This tool ships no board's figures; with
    no profile and no figure in the request, the routes that need one say so instead of
    inventing it (`GET /rig/profile` reports what is configured).

Every response from here carries `"experimental": true` and a short `"note"`, including the
503s, so a client can never render one of these numbers as if it were core.

THE DEPENDENCY RUNS ONE WAY. The bridge never imports this package by name: it finds it through
`extensions.discover()` and serves `ROUTES`. Nothing in the acquisition path imports it.
Acquisition is the job that is not allowed to fail, and an analysis tool that fails to import
must not be able to take a serial port down mid-session.
"""

import importlib.util as _ilu
import json
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


# --------------------------------------------------------------------- the rig profile (EXP) --
# A board's noise floor is a MEASUREMENT of that board, so it is never a constant of this tool.
# The user supplies it -- in each request, or once in a JSON file named by $OLIMEX_RIG_PROFILE:
#
#   {
#     "noise_floor_uv_rms": <number>,     # required: YOUR board's in-band noise floor, uV RMS
#     "provenance": "MEASURED",           # MEASURED | DATASHEET | RECALLED-VERIFY (the default)
#     "uv_per_count": <number>,           # optional: the scale that floor was measured with
#     "how_measured": "<free text>",      # optional: e.g. shorted inputs, resistor, duration, band
#     "notes": "<free text>"              # optional; anything else is kept and echoed back
#   }
#
# Only "MEASURED" can support a verdict in the companion noise-budget tool; anything else yields
# the shape of the answer, not the answer. See docs/experimental.md.

RIG_PROFILE_ENV = "OLIMEX_RIG_PROFILE"
PROFILE_PROVENANCES = ("MEASURED", "DATASHEET", "RECALLED-VERIFY")
NO_PROFILE = (
    "no rig profile is configured: pass `noise_floor_uv_rms` (and `provenance`) in the request, "
    "or set $OLIMEX_RIG_PROFILE to a JSON file describing your board (docs/experimental.md). "
    "This tool ships no board's noise figures."
)


class NoRigProfile(ValueError):
    """A route needed a noise floor and neither the request nor a rig profile supplied one."""


def load_rig_profile():
    """(profile, error). `profile` is None when nothing is configured or the file is unusable;
    `error` says why a configured file was refused. Re-read on every call, so editing the file
    needs no restart."""
    path = os.environ.get(RIG_PROFILE_ENV)
    if not path:
        return None, None
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"${RIG_PROFILE_ENV} = {path!r} could not be read as JSON: {e}"
    if not isinstance(raw, dict):
        return None, f"${RIG_PROFILE_ENV} must hold a JSON object"
    try:
        floor = float(raw["noise_floor_uv_rms"])
    except (KeyError, TypeError, ValueError):
        return None, f"${RIG_PROFILE_ENV} needs a numeric `noise_floor_uv_rms`"
    if not (0 < floor < float("inf")):
        return None, "`noise_floor_uv_rms` must be positive"
    prov = raw.get("provenance", "RECALLED-VERIFY")
    if prov not in PROFILE_PROVENANCES:
        return None, f"`provenance` must be one of {list(PROFILE_PROVENANCES)}, not {prov!r}"
    out = dict(raw)
    out.update(noise_floor_uv_rms=floor, provenance=prov, source=path, experimental=True)
    return out, None


def rig_profile_status():
    """What GET /rig/profile answers: the configured profile, or a plain statement that none is."""
    prof, err = load_rig_profile()
    if prof is not None:
        return {"configured": True, "profile": prof}
    out = {"configured": False, "profile": None, "reading": NO_PROFILE}
    if err:
        out["error"] = err
    return out


def _floor(body):
    """(noise_floor_uv_rms, provenance, uv_per_count, basis) from the request, else the profile."""
    if body.get("noise_floor_uv_rms") is not None:
        return (
            float(body["noise_floor_uv_rms"]),
            body.get("provenance", "RECALLED-VERIFY"),
            _opt(body, "uv_per_count"),
            "request",
        )
    prof, err = load_rig_profile()
    if prof is None:
        raise NoRigProfile(NO_PROFILE + (f" ({err})" if err else ""))
    upc = _opt(body, "uv_per_count")
    if upc is None and prof.get("uv_per_count") is not None:
        upc = float(prof["uv_per_count"])
    return prof["noise_floor_uv_rms"], prof["provenance"], upc, f"rig profile ({prof['source']})"


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
    """What a client needs to call the extraction endpoints correctly, including whatever rig
    profile the user configured (or the statement that none is)."""
    return {
        "syncSources": extract.SYNC_SOURCES,
        "hardwareControls": extract.HARDWARE_CONTROLS,
        "artifactLatencyFloorMs": extract.ARTIFACT_LATENCY_MS,
        "provenance": noise_budget.PROVENANCE,
        "verdictTiers": sorted(noise_budget.VERDICT_TIERS),
        "rigProfile": rig_profile_status(),
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

GET_ROUTES = ("/claims", "/atlas/reference", "/extract/reference", "/rig/profile")
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
ROUTE_NAMES = GET_ROUTES + tuple("POST " + p for p in ATLAS_POST + DETECTION_POST)


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
    if path == "/rig/profile":
        # Needs no companion tool: it only reports what the user configured.
        return 200, mark(rig_profile_status())
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
        try:
            out = _detection_post(path, body, samples_for, rate_for)
        except NoRigProfile as e:
            return 400, mark({"error": str(e), "rig_profile": rig_profile_status()})
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
        floor, prov, upc, basis = _floor(body)
        out = noise_budget.budget(
            float(body["target_nv"]),
            floor,
            prov,
            rate_hz=float(body.get("rate", DEFAULT_RATE)),
            snr_required=float(body.get("snr_required", 3.0)),
            sustain_window_s=_opt(body, "sustain_window_s"),
            uv_per_count=upc,
        )
        return dict(out, noise_floor_basis=basis)
    if path == "/detection-curve":
        floor, prov, upc, basis = _floor(body)
        out = _tone().detection_curve(
            floor,
            prov,
            rate_hz=float(body.get("rate", DEFAULT_RATE)),
            ref_hz=float(body.get("ref_hz", 40.0)),
            dwells_s=tuple(body.get("dwells_s", (1.0, 4.0, 16.0))),
            trials=int(body.get("trials", 8)),
            alpha=float(body.get("alpha", 0.01)),
            uv_per_count=upc,
            dither_probe=bool(body.get("dither_probe", False)),
        )
        return dict(out, noise_floor_basis=basis) if isinstance(out, dict) else out

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


# ------------------------------------------------------------------ the bridge contract --
# {(method, path): handler(body, ctx) -> (status, obj)}. See docs/EXTENSIONS.md.


def _get_handler(path):
    def handler(_query, _ctx):
        return handle_get(path)

    handler.__name__ = "get_" + path.strip("/").replace("/", "_").replace("-", "_")
    return handler


def _post_handler(path):
    def handler(body, ctx):
        return handle_post(path, body, samples_for=ctx.samples_for, rate_for=ctx.rate_for)

    handler.__name__ = "post_" + path.strip("/").replace("/", "_").replace("-", "_")
    return handler


ROUTE_TABLE = {("GET", p): _get_handler(p) for p in GET_ROUTES}
ROUTE_TABLE.update({("POST", p): _post_handler(p) for p in ATLAS_POST + DETECTION_POST})


def health():
    """What /health shows for this extension: which companion tools were found, and where."""
    return {
        "atlas": _HAVE_ATLAS,
        "atlasError": _ATLAS_ERROR,
        "detection": _HAVE_DETECTION,
        "detectionError": _DETECTION_ERROR,
        "toolsDir": TOOLS_DIR,
        "rigProfile": rig_profile_status()["configured"],
    }
