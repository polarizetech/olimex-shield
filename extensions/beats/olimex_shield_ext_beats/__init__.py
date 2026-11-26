"""olimex_shield_ext_beats: heartbeats from the live ECG, as R-peak times and R-R intervals.

EXPLORATORY (scope/ecg-beats.md). The detector is detect.py (Elgendi 2013). See docs/EXTENSIONS.md.
"""

__version__ = "0.1.0"
#: The olimex-shield releases this was built and tested against. Enforced on import; must equal
#: `[tool.olimex-shield] requires` in pyproject.toml.
REQUIRES = ">=0.3.0,<0.4"

import threading  # noqa: E402
import time  # noqa: E402

from extensions import declare as _declare  # noqa: E402

from . import detect  # noqa: E402

EXTENSION = _declare(
    name="olimex-shield-ext-beats",
    module=__name__,
    version=__version__,
    requires=REQUIRES,
    job="Reports heartbeats from the live ECG: each R peak's time and the R-R interval.",
    uses=("extensions.Context.samples_for", "extensions.Context.rate_for"),
    extends={},
)

WINDOW_S = 5.0  # the seconds of the live ring searched on each request (build)
KEEP = 64  # beats remembered, to number each one once (build)
METHOD = "Elgendi 2013, doi:10.1371/journal.pone.0073557 (two event-related moving averages)"

_LOCK = threading.Lock()
_STATE = {"k": 0, "beats": []}


def _beats(query, ctx):
    """GET /beats[?seconds=s]: the beats in the last s seconds of the live ring,
    each numbered once."""
    body = {"source": "live", "seconds": query.get("seconds", WINDOW_S)}
    try:
        rate, basis = ctx.rate_for(body)
        x = ctx.samples_for(body)
    except ValueError as e:
        return 409, {"error": str(e), "beats": []}
    now = time.time()
    n = len(x)
    out = []
    with _LOCK:
        for i in detect.r_peaks(x, rate):
            t = now - (n - 1 - i) / rate
            known = next((b for b in _STATE["beats"] if abs(b["t"] - t) < detect.W1_S), None)
            if known is None:
                prev = _STATE["beats"][-1] if _STATE["beats"] else None
                _STATE["k"] += 1
                rr = t - prev["t"] if prev is not None and t > prev["t"] else None
                known = {"k": _STATE["k"], "t": t, "rr_s": rr}
                _STATE["beats"].append(known)
                del _STATE["beats"][:-KEEP]
            out.append(dict(known, age_s=now - known["t"]))
    return 200, {
        "now": now,
        "rate": rate,
        "rate_basis": basis,
        "window_s": n / rate if rate else 0.0,
        "beats": out,
        "method": METHOD,
        "params": {
            "low_hz": detect.LOW_HZ,
            "high_hz": detect.HIGH_HZ,
            "order": detect.ORDER,
            "w1_s": detect.W1_S,
            "w2_s": detect.W2_S,
            "beta": detect.BETA,
        },
    }


def mark(obj):
    """Every answer is exploratory."""
    return dict(
        obj,
        experimental=True,
        note="Exploratory R-peak times from a personal rig, not a medical device; "
        "nothing here is a finding.",
    )


#: The bridge contract: {(method, path): handler}.
ROUTES = {("GET", "/beats"): _beats}
