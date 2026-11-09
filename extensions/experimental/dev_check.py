#!/usr/bin/env python3
"""dev_check.py -- the gate of olimex-shield-ext-experimental.

Re-run it against every new olimex-shield MINOR before widening REQUIRES (docs/EXTENSIONS.md).
It checks the extension's own behaviour: every answer marked experimental, the rig profile read
from the user (never shipped), the companion tools switched off cleanly when absent, and, when
they are present, parity with the core's Goertzel copy and the merged claims registers.

Run: python3 extensions/experimental/dev_check.py
Stdlib only. No network, no device.
"""

import json
import math
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO / "apps" / "server"), str(HERE)]

import olimex_shield_ext_experimental as ext  # noqa: E402
import quality  # noqa: E402
from olimex_shield_ext_experimental import routes as X  # noqa: E402

import extensions as kit  # noqa: E402  the kit, from the bridge

PASS = FAIL = 0
FAILURES = []
FS = 250.0


def ok(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")


print("olimex-shield-ext-experimental")

# ------------------------------------------------------------------------- the declaration --
ok("it declared itself to the kit", ext.EXTENSION in kit.loaded())
ok(
    "...against the olimex-shield it is running on",
    kit.satisfies(kit.tool_version(), ext.REQUIRES) and ext.EXTENSION.tool_version,
)
ok(
    "ROUTES follows the bridge contract: (METHOD, path) -> callable",
    all(m in kit.METHODS and p.startswith("/") and callable(h) for (m, p), h in ext.ROUTES.items()),
)
ok(
    "the catalogue lists exactly its routes",
    {f"{m} {p}" for (m, p) in ext.ROUTES}
    == {
        r
        for e in kit.load_catalog()["extensions"]
        if e["name"] == ext.EXTENSION.name
        for r in e["routes"]
    },
)
ok(
    "it ships no board's measured figures: no noise table, no rate-error snapshot",
    not any(
        hasattr(X, k)
        for k in ("MEASURED_RIG", "RECALLED", "NOISE_NV_AT_40HZ", "RATE_ERROR_PPM_SNAPSHOT")
    ),
)
_m = ext.mark({"x": 1})
ok("mark() stamps experimental and the note", _m["experimental"] is True and _m["note"] == X.NOTE)
ok("...and wraps a non-dict", ext.mark([1])["result"] == [1])
_h = ext.health()
ok(
    "health() says which companion tools were found",
    {"atlas", "detection", "toolsDir", "rigProfile"} <= set(_h),
)

# ------------------------------------------------------------------- the companion tools --
_ctx = kit.Context(samples_for=lambda b: [0.0] * 10, rate_for=lambda b: (FS, "caller"))
if X._HAVE_DETECTION:
    _x = [math.sin(2 * math.pi * 10 * k / FS) + 0.1 * math.cos(k) for k in range(500)]
    ok(
        "quality's Goertzel copy is identical to signal-detection's",
        all(
            quality._goertzel_power(_x, FS, b, 500) == X.extract._goertzel_power(_x, FS, b, 500)
            for b in (3, 20, 40, 97)
        ),
    )
    if X._HAVE_ATLAS:
        ok(
            "with the tools present, /claims merges both registers",
            X.all_claims()["counts"]["evidence"]
            == len(X.atlas_claims.EVIDENCE) + len(X.detection_claims.EVIDENCE),
        )
    _code, _body = ext.ROUTES[("GET", "/claims")]({}, _ctx)
    ok(
        "...and every experimental response says it is experimental",
        _code == 200 and _body["experimental"] is True and _body["note"],
    )
else:
    print("  SKIP Goertzel parity and merged claims -- signal-detection tool not reachable")
    _code, _body = ext.ROUTES[("POST", "/extract")]({}, _ctx)
    ok(
        "without the tools a route answers 503, marked experimental, saying where it comes from",
        _code == 503 and _body["experimental"] is True and "OLIMEX_TOOLS" in _body["hint"],
    )

# ------------------------------------------------------------------------- the rig profile --
# The rig profile: a board's noise floor is the USER's measurement, never a constant shipped here.
_saved_prof = os.environ.pop("OLIMEX_RIG_PROFILE", None)
_st = X.rig_profile_status()
ok(
    "with no $OLIMEX_RIG_PROFILE, the bridge says plainly that no rig profile is configured",
    _st["configured"] is False and _st["profile"] is None and "no rig profile" in _st["reading"],
)
_code, _body = X.handle_get("/rig/profile")
ok(
    "...GET /rig/profile answers that without any companion tool, marked experimental",
    _code == 200 and _body["configured"] is False and _body["experimental"] is True,
)
try:
    X._floor({})
    _raised = False
except X.NoRigProfile as _e:
    _raised = "OLIMEX_RIG_PROFILE" in str(_e) and "noise_floor_uv_rms" in str(_e)
ok("...and a route needing a floor refuses rather than inventing one", _raised)
ok(
    "...while a floor in the request is used as given, and labelled as the request's",
    X._floor({"noise_floor_uv_rms": 2.5, "provenance": "MEASURED"})
    == (2.5, "MEASURED", None, "request"),
)
_tmp_prof = Path(tempfile.mkdtemp()) / "rig_profile.json"
try:
    _tmp_prof.write_text(
        json.dumps({"noise_floor_uv_rms": 1.25, "provenance": "MEASURED", "uv_per_count": 4.0})
    )
    os.environ["OLIMEX_RIG_PROFILE"] = str(_tmp_prof)
    _st = X.rig_profile_status()
    ok(
        "a user-supplied profile is read, echoed and marked experimental",
        _st["configured"] is True
        and _st["profile"]["noise_floor_uv_rms"] == 1.25
        and _st["profile"]["experimental"] is True,
        str(_st),
    )
    _f = X._floor({})
    ok(
        "...and supplies the floor, provenance and scale when the request does not",
        _f[:3] == (1.25, "MEASURED", 4.0) and "rig profile" in _f[3],
        str(_f),
    )
    ok(
        "...but a request's own floor still wins over the profile",
        X._floor({"noise_floor_uv_rms": 9.0})[0] == 9.0,
    )
    for _bad_prof, _why in (
        ({"provenance": "MEASURED"}, "no floor"),
        ({"noise_floor_uv_rms": -1}, "a negative floor"),
        ({"noise_floor_uv_rms": 1, "provenance": "GUESSED"}, "an unknown provenance"),
    ):
        _tmp_prof.write_text(json.dumps(_bad_prof))
        _st = X.rig_profile_status()
        ok(
            f"...and a profile with {_why} is refused, saying why",
            not _st["configured"] and _st.get("error"),
        )
    _tmp_prof.write_text("{not json")
    ok("...and so is a file that is not JSON", X.rig_profile_status().get("error"))
finally:
    _tmp_prof.unlink(missing_ok=True)
    os.environ.pop("OLIMEX_RIG_PROFILE", None)
    if _saved_prof is not None:
        os.environ["OLIMEX_RIG_PROFILE"] = _saved_prof


print(f"\n{PASS}/{PASS + FAIL} checks passed")
for f in FAILURES:
    print("  FAIL", f)
sys.exit(1 if FAIL else 0)
