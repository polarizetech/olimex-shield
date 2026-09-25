#!/usr/bin/env python3
"""dev_check_sessions.py -- the session store's gate. Mostly refusals: they are the contract."""

import ast
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
P, F = [], []


def ok(n, c, note=""):
    (P if c else F).append(f"{n}{(' -- ' + note) if note else ''}")


def raises(name, fn, contains=""):
    try:
        fn()
        ok(name, False, "did not raise")
    except Exception as e:
        ok(name, contains.lower() in str(e).lower(), f"{type(e).__name__}: {str(e)[:80]}")


with tempfile.TemporaryDirectory() as d:
    os.environ.pop("OLIMEX_SESSIONS", None)
    os.environ["BIOSIGNAL_DATASET"] = d
    import sessions as D

    ok(
        "the store honours $BIOSIGNAL_DATASET (its earlier name)",
        str(D.store_root()) == d,
    )
    os.environ["OLIMEX_SESSIONS"] = d
    ok("...and $OLIMEX_SESSIONS, which wins", str(D.store_root()) == d)
    _saved = {k: os.environ.pop(k) for k in ("OLIMEX_SESSIONS", "BIOSIGNAL_DATASET")}
    ok("the default is <repo>/sessions", D.store_root() == HERE.parents[1] / "sessions")
    os.environ.update(_saved)
    ok(
        "...and <repo>/sessions is gitignored, so a recording is never committed by accident",
        "sessions/" in (HERE.parents[1] / ".gitignore").read_text().split(),
    )
    for bad in ("../etc", "a/b", ".hidden", ""):
        raises(
            f"a session id that is not a plain stamp is refused ({bad!r})",
            lambda b=bad: D.session_dir(b),
            "not a session id",
        )

    # --- stdlib only. A recording that fails because a maths library moved is a session
    # that cannot be redone.
    mods = set()
    for n in ast.walk(ast.parse((HERE / "sessions.py").read_text())):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mods.add(n.module.split(".")[0])
    ok(
        "sessions.py imports nothing but the stdlib",
        not (mods - {"csv", "json", "os", "time", "dataclasses", "pathlib", "__future__"}),
        f"{sorted(mods)}",
    )

    # --- the refusals
    raises(
        "a session with no project is refused",
        lambda: D.start({"readout": "ecg", "source": "synthetic"}),
        "needs 'project'",
    )
    raises(
        "a session with no readout is refused",
        lambda: D.start({"project": "p", "source": "synthetic"}),
        "needs 'readout'",
    )
    raises(
        "an unknown source is refused",
        lambda: D.start({"project": "p", "readout": "ecg", "source": "vibes"}),
        "source must be",
    )
    raises(
        "an electrode session with no electrodes_on_at is refused",
        lambda: D.start({"project": "p", "readout": "ecg", "source": "electrode"}),
        "electrodes_on_at",
    )
    raises(
        "a tag carrying an expected result is refused",
        lambda: D._scan_forbidden({"label": "x", "expected": "alpha drops"}),
        "may not carry what it is expected to do",
    )
    raises(
        "...at any depth",
        lambda: D._scan_forbidden({"a": [{"b": {"hypothesis": 1}}]}),
        "may not carry",
    )
    ok(
        "the forbidden list covers the obvious synonyms",
        {"expect", "hypothesis", "predicted", "should", "conclusion"} <= set(D.FORBIDDEN_TAG_KEYS),
    )

    # --- the round trip
    r = D.start({"project": "gate", "readout": "ecg", "source": "synthetic", "rate_hz": 100.0})
    st = r["stamp"]
    ok(
        "a synthetic session says so and cannot forget to",
        "MEASURED" in r["meta"]["synthetic_warning"],
    )
    raises(
        "a tag with no t_s is refused", lambda: D.tag({"stamp": st, "label": "x"}), "needs `t_s`"
    )
    raises(
        "a tag on an unknown session is refused",
        lambda: D.tag({"stamp": "nope", "label": "x", "t_s": 1.0}),
        "no open session",
    )
    D.append({"stamp": st, "values": [1.0] * 250})
    D.tag({"stamp": st, "label": "looked at colour", "t_s": 0.5})
    D.tag({"stamp": st, "label": "looked at colour", "t_s": 1.5})  # 250 @ 100 Hz = 2.5 s
    m = D.stop({"stamp": st})["meta"]
    ok("tag counts survive to the sidecar", m["tag_counts"] == {"looked at colour": 2})
    ok(
        "the rate is MEASURED, not nominal",
        m["effective_rate_hz"] != m["rate_hz"] and m["n_samples"] == 250,
    )
    ok(
        "every tag lands inside the session's SAMPLES",
        m["tags_outside_samples"] == 0,
        m.get("tag_clock_warning", ""),
    )

    # THE CLOCK BUG, pinned. A writer that zeroes its tag clock at connect rather than at
    # record produces tags beyond the end of its own samples -- silent, and it misaligns
    # every one of them. The session is still written; the sidecar says so.
    r2 = D.start({"project": "gate", "readout": "ecg", "source": "synthetic", "rate_hz": 100.0})
    D.append({"stamp": r2["stamp"], "values": [1.0] * 100})  # 1 s of samples
    D.tag({"stamp": r2["stamp"], "label": "late", "t_s": 77.0})  # ...tagged at 77 s
    m2 = D.stop({"stamp": r2["stamp"]})["meta"]
    ok(
        "a tag beyond the end of its own samples is FLAGGED, not silently stored",
        m2["tags_outside_samples"] == 1
        and "zeroed its clock at connect" in m2["tag_clock_warning"],
    )
    ok(
        "...and the recording is kept anyway -- a metadata fault must not destroy samples",
        m2["n_samples"] == 100 and len(m2["tags"]) == 1,
    )

    # --- the chain version and the mains frequency are stamped at creation
    ok(
        "a session records the software version that made it (from pyproject.toml)",
        m.get("software_version") == D.software_version() != "unknown",
        str(m.get("software_version")),
    )
    _saved = os.environ.pop("OLIMEX_MAINS_HZ", None)
    ok("mains_hz is null when nobody said -- never assumed", m.get("mains_hz") is None)
    _r50 = D.start({"project": "gate", "readout": "ecg", "source": "synthetic", "mains_hz": 50})
    D.stop({"stamp": _r50["stamp"]})
    ok("...the caller's mains_hz is kept", _r50["meta"]["mains_hz"] == 50.0)
    os.environ["OLIMEX_MAINS_HZ"] = "60"
    _r60 = D.start({"project": "gate", "readout": "ecg", "source": "synthetic"})
    D.stop({"stamp": _r60["stamp"]})
    ok("...else $OLIMEX_MAINS_HZ", _r60["meta"]["mains_hz"] == 60.0)
    os.environ.pop("OLIMEX_MAINS_HZ")
    if _saved is not None:
        os.environ["OLIMEX_MAINS_HZ"] = _saved
    raises(
        "a mains_hz that is not a number is refused",
        lambda: D.start({"project": "g", "readout": "ecg", "source": "synthetic", "mains_hz": "x"}),
        "mains_hz",
    )
    _orig_root = D.ROOT
    D.ROOT = Path(d) / "no-such-repo"
    ok(
        "with no pyproject.toml the version is 'unknown', not a guess",
        D.software_version() == "unknown",
    )
    D.ROOT = _orig_root

    # --- reading it back, which is the point
    cat = D.catalogue()
    ok("the session is in the catalogue", any(c["stamp"] == st for c in cat))
    ok(
        "two sessions in the same second do NOT collide -- that was silent data loss",
        r2["stamp"] != st and len({c["stamp"] for c in cat}) == len(cat) >= 2,
        f"{[c['stamp'] for c in cat]}",
    )
    ok(
        "catalogue() is not project-scoped by default -- other projects can read it",
        D.catalogue.__defaults__ == (None,),
    )
    ok("and can be scoped when you want it", D.catalogue("nobody") == [])
    back = D.load(st)
    ok("load() returns the samples", len(back["values"]) == 250)
    ok("...and the tags with them", len(back["tags"]) == 2)
    ok("...and can be asked for metadata only", "values" not in D.load(st, values=False))
    raises("loading an unknown session raises", lambda: D.load("nope"), "no session")

    # --- annotate: facts learned after start, never a rewrite
    raises(
        "annotating an open session is refused",
        lambda: D.annotate(
            {"stamp": r2["stamp"] if r2["stamp"] in D._OPEN else "zz", "rate_measured_hz": 1}
        ),
        "",
    )
    D.annotate({"stamp": st, "rate_measured_hz": 249.83, "rate_basis": "host clock"})
    ok(
        "annotate adds the measured rate to a finished session",
        D.load(st, values=False)["meta"]["rate_measured_hz"] == 249.83,
    )
    raises(
        "...but may not add anything else",
        lambda: D.annotate({"stamp": st, "source": "electrode"}),
        "may only add",
    )
    raises(
        "...and never rewrites a value already there",
        lambda: D.annotate({"stamp": st, "rate_measured_hz": 250.0}),
        "not rewritten",
    )
    D.annotate({"stamp": st, "stream_parse_errors": 0, "stream_gaps": 2, "stream_max_gap_us": 8000})
    _mm = D.load(st, values=False)["meta"]
    ok(
        "annotate may add what the wire lost (from the bridge's /record/stop)",
        _mm["stream_gaps"] == 2
        and _mm["stream_parse_errors"] == 0
        and _mm["stream_max_gap_us"] == 8000,
    )

    # --- routing
    payload, code = D.handle("/dataset/sessions", None, {})
    ok("the router lists sessions", code == 200 and payload["sessions"])
    payload, code = D.handle("/dataset/nonsense", None, {})
    ok("an unknown route is a 404 with a reason", code == 404 and "error" in payload)
    payload, code = D.handle("/dataset/start", {"readout": "x"})
    ok("a bad body is a 400 with the reason, never a crash", code == 400)

DOC = (HERE / "sessions.py").read_text()
ok(
    "the privacy posture is written down, not assumed",
    "PHYSIOLOGICAL RECORD PLUS A DIARY" in DOC and "only to a private target" in DOC,
)

for f in F:
    print(f"  FAIL {f}")
print(f"\nsessions/dev_check: {len(P)}/{len(P) + len(F)} passed")
sys.exit(1 if F else 0)
