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
    uses=(
        "extensions.Context.samples_for",
        "extensions.Context.rate_for",
        "extensions.Context.timed_samples_for",
    ),
    extends={},
)

WINDOW_S = 5.0  # the seconds of the live ring searched on each request (build)
KEEP = 64  # beats remembered, to number each one once (build)
MOD = 2**32  # the board's micros() wraps here (apps/server/timebase.py T_US_MODULUS)
METHOD = "Elgendi 2013, doi:10.1371/journal.pone.0073557 (two event-related moving averages)"

_LOCK = threading.Lock()
_STATE = {"k": 0, "beats": []}


def _since_us(a, b):
    """Board microseconds from stamp b to stamp a, across the 2**32 wrap."""
    return (a - b) % MOD


def _beats(query, ctx):
    """GET /beats[?seconds=s]: the beats in the last s seconds of the live ring, each numbered once.
    Each beat's time is the board's own t_us stamp of its R-peak sample,
    exactly as the board sent it."""
    body = {"source": "live", "seconds": query.get("seconds", WINDOW_S)}
    if getattr(ctx, "timed_samples_for", None) is None:
        return 409, {
            "error": "this bridge does not give the board's clock to extensions",
            "beats": [],
        }
    try:
        rate, basis = ctx.rate_for(body)
        got = ctx.timed_samples_for(body)
    except ValueError as e:
        return 409, {"error": str(e), "beats": []}
    x, tus, arrived = got["samples"], got["t_us"], got["arrived"]
    if not tus or any(tu is None for tu in tus):
        return 409, {
            "error": "the board sends no t_us, so beat times cannot come from its clock",
            "beats": [],
        }
    now = time.time()
    newest = tus[-1]
    out = []
    with _LOCK:
        for i in detect.r_peaks(x, rate):
            tu = tus[i]
            known = next(
                (
                    b
                    for b in _STATE["beats"]
                    if min(_since_us(tu, b["t_us"]), _since_us(b["t_us"], tu)) < detect.W1_S * 1e6
                ),
                None,
            )
            if known is None:
                prev = _STATE["beats"][-1] if _STATE["beats"] else None
                _STATE["k"] += 1
                rr = None
                if prev is not None and 0 < _since_us(tu, prev["t_us"]) < MOD // 2:
                    rr = _since_us(tu, prev["t_us"]) / 1e6
                known = {"k": _STATE["k"], "t_us": tu, "rr_s": rr}
                _STATE["beats"].append(known)
                del _STATE["beats"][:-KEEP]
            out.append(dict(known, behind_newest_s=_since_us(newest, known["t_us"]) / 1e6))
    return 200, {
        "now": now,
        "newest_t_us": newest,
        "newest_arrived": arrived,
        "clock": (
            "board t_us (micros(), wraps at 2**32); now and newest_arrived are host time.time()"
        ),
        "rate": rate,
        "rate_basis": basis,
        "window_s": len(x) / rate if rate else 0.0,
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
