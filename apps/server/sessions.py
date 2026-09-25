"""sessions.py -- the session store: samples plus a sidecar carrying provenance and the TAG track.

Stdlib only. The workbench (`apps/web/serve.py`) and any host server mount `handle()` at
`/dataset/*`; `<signal-panel>`'s Record button writes through it.

Where sessions go: `$OLIMEX_SESSIONS`, else `$BIOSIGNAL_DATASET` (this store's earlier name,
honoured so sessions recorded under it stay readable), else `<repo>/sessions/`, which is
gitignored.

*** A SESSION IS A PHYSIOLOGICAL RECORD PLUS A DIARY. ***

The tag track says what a person was doing at each second. That is more revealing than the
waveform. Nothing here uploads, publishes or serves a session anywhere by itself; `storage.py`
does that only when configured, and only to a private target.

The refusals below were each bought by a real failure; the comments say which.
"""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# Legacy identifier from this store's earlier name, kept so existing sidecars still load.
SCHEMA = "biosignal-dataset.session/1"

ROOT = Path(__file__).resolve().parents[2]


def software_version() -> str:
    """The measuring chain's version: `version` under `[project]` in the repo's pyproject.toml.

    Parsed with plain string handling (tomllib is 3.11+ and this must run on 3.9). "unknown" when
    the file or the key is missing -- never a guess.
    """
    try:
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line.strip("[]").strip()
            continue
        if section == "project" and line.startswith("version"):
            key, _, val = line.partition("=")
            if key.strip() == "version":
                val = val.strip().strip("\"'")
                return val or "unknown"
    return "unknown"


def store_root() -> Path:
    """`$OLIMEX_SESSIONS`, else `$BIOSIGNAL_DATASET`, else `<repo>/sessions`."""
    env = os.environ.get("OLIMEX_SESSIONS") or os.environ.get("BIOSIGNAL_DATASET")
    return Path(env).expanduser() if env else ROOT / "sessions"


def session_dir(stamp: str) -> Path:
    """The directory of one session. Refuses anything that is not a plain stamp: `load()` and
    every uploader take a stamp from a request, and `../..` would otherwise walk out of the
    store."""
    stamp = str(stamp or "")
    if not stamp or "/" in stamp or "\\" in stamp or stamp.startswith("."):
        raise DatasetError(f"not a session id: {stamp!r}")
    return store_root() / stamp


#: `synthetic` can never be absent by omission -- a synthetic trace that forgets to say so is
#: the one failure a dataset cannot recover from after the fact.
SOURCES = ("electrode", "synthetic", "replay")

#: A TAG MAY NOT CARRY WHAT IT IS EXPECTED TO DO. A description of what was delivered that also
#: states the hypothesis has smuggled it into the only thing the analysis is allowed to see.
#: Checked at any depth.
FORBIDDEN_TAG_KEYS = (
    "expect",
    "expected",
    "hypothesis",
    "predict",
    "predicted",
    "should",
    "outcome",
    "result",
    "conclusion",
)


class DatasetError(ValueError):
    pass


@dataclass
class Session:
    stamp: str
    meta: dict
    dir: Path
    n: int = 0
    _fh: object = None
    _writer: object = None
    tags: list = field(default_factory=list)

    @property
    def csv_path(self) -> Path:
        return self.dir / "samples.csv"

    @property
    def json_path(self) -> Path:
        return self.dir / "session.json"


_OPEN: dict = {}


def _require(body, key):
    v = body.get(key)
    if v is None or (isinstance(v, str) and not str(v).strip()):
        raise DatasetError(f"a session needs {key!r}")
    return v


def start(body: dict) -> dict:
    """Open a session. `project` and `readout` are required -- a recording nobody can trace
    back to what it was of is not a dataset entry, it is a file."""
    source = body.get("source") or "electrode"
    if source not in SOURCES:
        raise DatasetError(f"source must be one of {SOURCES}, not {source!r}")
    project = _require(body, "project")
    readout = _require(body, "readout")
    if source == "electrode" and not body.get("electrodes_on_at"):
        raise DatasetError(
            "an electrode session needs `electrodes_on_at` (epoch seconds, when the "
            "electrodes actually went on). Defaulting it to now asserts ZERO settling, and "
            "the settling window is what separates the instrument's own disturbance from the "
            "subject's."
        )
    # *** A COLLIDING STAMP DESTROYS A RECORDING, SILENTLY. ***
    # The stamp has one-second resolution, so two sessions started by the same project in the
    # same second produced the SAME directory and the second overwrote the first -- found by
    # a gate that started two sessions in a test and got one back. `exist_ok=True` on a
    # directory that already holds a session is data loss wearing a convenience flag.
    mains_hz = _mains_hz(body.get("mains_hz"))  # validated BEFORE anything is created on disk
    base = time.strftime("%Y%m%d-%H%M%S") + f"-{project}"
    stamp, n = base, 1
    while (store_root() / stamp).exists():
        n += 1
        stamp = f"{base}-{n}"
    d = store_root() / stamp
    d.mkdir(parents=True)
    meta = {
        "schema": SCHEMA,
        "stamp": stamp,
        "project": project,
        "readout": readout,
        "source": source,
        "site": body.get("site") or "",
        "montage": body.get("montage") or [],
        "rate_hz": float(body.get("rate_hz") or 0.0),
        "uv_per_count": body.get("uv_per_count"),
        "already_uv": bool(body.get("already_uv")),
        "electrodes_on_at": body.get("electrodes_on_at"),
        "started_at": time.time(),
        "operator_is_subject": bool(body.get("operator_is_subject", True)),
        "black_box": body.get("black_box"),
        "front_end": body.get("front_end"),
        "notes": body.get("notes") or "",
        # The measuring chain that made this session (pyproject.toml), so a recording can be
        # matched to a tagged release.
        "software_version": software_version(),
        # Mains frequency where the recording was made: the caller's, else $OLIMEX_MAINS_HZ, else
        # null -- never assumed. The BIDS export writes PowerLineFrequency from it ("n/a" if null).
        "mains_hz": mains_hz,
        "tags": [],
    }
    if source == "synthetic":
        meta["synthetic_warning"] = (
            "SYNTHETIC. Nothing in this session came off an electrode, and no reading taken "
            "from it may wear a MEASURED badge."
        )
    s = Session(stamp=stamp, meta=meta, dir=d)
    # Held open across append() calls until the session is closed, so not a `with` block.
    s._fh = open(s.csv_path, "w", newline="")  # noqa: SIM115
    s._writer = csv.writer(s._fh)
    s._writer.writerow(["sample_index", "value"])
    _OPEN[stamp] = s
    _write_meta(s)
    return {"stamp": stamp, "meta": meta}


def _mains_hz(v):
    if v is None or v == "":
        v = os.environ.get("OLIMEX_MAINS_HZ")
    try:
        f = float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        raise DatasetError(f"mains_hz must be a number, not {v!r}") from None
    return f if f and f > 0 else None


def append(body: dict) -> dict:
    s = _OPEN.get(body.get("stamp"))
    if s is None:
        raise DatasetError(f"no open session {body.get('stamp')!r}")
    for v in body.get("values") or []:
        s._writer.writerow([s.n, v])
        s.n += 1
    s._fh.flush()
    return {"stamp": s.stamp, "n": s.n}


def _scan_forbidden(obj, path="tag"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(f in str(k).lower() for f in FORBIDDEN_TAG_KEYS):
                raise DatasetError(
                    f"{path}.{k}: a tag may not carry what it is expected to do. A record of "
                    f"what was delivered that also states the hypothesis has smuggled it into "
                    f"the only thing the analysis is allowed to see. Put it in the session "
                    f"notes, or in a preregistration -- not on the tag."
                )
            _scan_forbidden(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _scan_forbidden(v, f"{path}[{i}]")


def tag(body: dict) -> dict:
    """`{stamp, label, t_s, note?}` -- `t_s` is seconds since this session's FIRST SAMPLE.

    There is deliberately no wall-clock fallback. A wall-clock tag inherits every scheduling
    delay between the browser and the daemon that holds the port, and the sample index is the
    only clock both halves share. What remains -- the operator's own reaction time -- is real,
    unmeasured, and is why any analysis of these tags needs a wide window and a deadband.
    """
    s = _OPEN.get(body.get("stamp"))
    if s is None:
        raise DatasetError(f"no open session {body.get('stamp')!r}")
    _scan_forbidden(body)
    label = str(_require(body, "label")).strip()
    t_s = body.get("t_s")
    if t_s is None:
        raise DatasetError(
            "a tag needs `t_s`, seconds since this session's first sample. There is no "
            "wall-clock fallback by design -- see this function's docstring."
        )
    rec = {
        "label": label,
        "t_s": float(t_s),
        "note": str(body.get("note") or ""),
        "wall_s": time.time(),
    }
    s.tags.append(rec)
    s.meta["tags"] = s.tags
    _write_meta(s)
    return {"stamp": s.stamp, "n_tags": len(s.tags), "tag": rec}


def stop(body: dict) -> dict:
    s = _OPEN.pop(body.get("stamp"), None)
    if s is None:
        raise DatasetError(f"no open session {body.get('stamp')!r}")
    try:
        s._fh.flush()
        s._fh.close()
    except OSError:
        pass
    m = s.meta
    m["stopped_at"] = time.time()
    m["n_samples"] = s.n
    dur = max(m["stopped_at"] - m["started_at"], 1e-9)
    # MEASURED, not nominal. A throttled tab starves the source, and a sidecar that reported
    # the nominal rate would let a reader conclude the record was resampled.
    m["duration_s"] = dur
    m["effective_rate_hz"] = s.n / dur
    m["tags"] = s.tags
    # *** A TAG OUTSIDE ITS OWN SAMPLES IS A CLOCK BUG, AND IT IS SILENT. ***
    # This is checked at stop() rather than at tag() because during a recording a tag can
    # legitimately precede the batch that carries its samples. The bug it catches is real and
    # was hit for real: a panel that zeroed its tag clock at CONNECT rather than at RECORD
    # produced a 23 s session with tags at 77 s, and nothing on screen looked wrong. The
    # session is still written -- refusing it would destroy the recording over a metadata
    # fault -- but the sidecar says so, and so does anything that reads it.
    # The span is in the SIGNAL's time base, so it uses the declared acquisition rate rather
    # than the wall-clock effective rate -- a fast writer can append a minute of samples in a
    # millisecond, which makes the effective rate meaningless for this check while leaving
    # the samples perfectly valid.
    _r = m["rate_hz"] or m["effective_rate_hz"]
    span = s.n / _r if _r else 0.0
    outside = [t for t in s.tags if not (0.0 <= t["t_s"] <= span + 1.0)]
    m["tags_outside_samples"] = len(outside)
    if outside:
        m["tag_clock_warning"] = (
            f"{len(outside)} of {len(s.tags)} tags fall outside this session's {span:.1f} s of "
            f"samples (worst: {max(abs(t['t_s']) for t in outside):.1f} s). A tag's t_s must "
            f"be seconds since this session's FIRST SAMPLE. This usually means the writer "
            f"zeroed its clock at connect rather than at record. The samples and the tags are "
            f"BOTH kept, and they cannot be aligned until the offset is known."
        )
    counts: dict = {}
    for t in s.tags:
        counts[t["label"]] = counts.get(t["label"], 0) + 1
    m["tag_counts"] = counts
    _write_meta(s)
    return {"stamp": s.stamp, "meta": m}


#: What `annotate()` may add to a FINISHED session. Deliberately narrow: facts learned only after
#: the recording started (the bridge's measured rate needs ~30 s) or when it was uploaded. It may
#: not rewrite anything the session already says -- a sidecar edited after the fact is a sidecar
#: nobody can trust.
ANNOTATABLE = (
    "rate_measured_hz",
    "rate_error_ppm",
    "rate_uncertainty_ppm",
    "rate_basis",
    "hookup_confirmed_at",
    # What the wire lost while the bridge's black box was armed for this session (the bridge's
    # /record/stop reports them; see serve.py). Counted from the board's t_us, never repaired.
    "stream_parse_errors",
    "stream_gaps",
    "stream_max_gap_us",
    "stream_integrity_basis",
)


def annotate(body: dict) -> dict:
    stamp = body.get("stamp")
    d = session_dir(stamp)
    j = d / "session.json"
    if not j.is_file():
        raise DatasetError(f"no session {stamp!r}")
    if stamp in _OPEN:
        raise DatasetError(f"{stamp!r} is still recording; annotate it after stop")
    extra = sorted(set(body) - {"stamp"} - set(ANNOTATABLE))
    if extra:
        raise DatasetError(f"annotate() may only add {ANNOTATABLE}; refused {extra}")
    meta = json.loads(j.read_text())
    clash = [k for k in ANNOTATABLE if k in body and meta.get(k) not in (None, body[k])]
    if clash:
        raise DatasetError(f"{clash} already set on {stamp!r}; annotations are not rewritten")
    for k in ANNOTATABLE:
        if body.get(k) is not None:
            meta[k] = body[k]
    j.write_text(json.dumps(meta, indent=2))
    return {"stamp": stamp, "annotated": [k for k in ANNOTATABLE if body.get(k) is not None]}


def _write_meta(s: Session):
    s.json_path.write_text(json.dumps(s.meta, indent=2))


def catalogue(project: str | None = None) -> list:
    """Every session in the store, newest first. `project=None` means ALL of them -- which is
    the point: a project can read what another project recorded."""
    root = store_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        j = d / "session.json"
        if not j.is_file():
            continue
        try:
            m = json.loads(j.read_text())
        except (OSError, ValueError):
            continue
        if project and m.get("project") != project:
            continue
        out.append(
            {
                k: m.get(k)
                for k in (
                    "stamp",
                    "project",
                    "readout",
                    "source",
                    "site",
                    "n_samples",
                    "duration_s",
                    "effective_rate_hz",
                    "tag_counts",
                    "rate_hz",
                    "rate_measured_hz",
                    "started_at",
                    "software_version",
                    "stream_gaps",
                    "stream_parse_errors",
                )
            }
            | {"n_tags": len(m.get("tags") or []), "open": m.get("stamp") in _OPEN}
        )
    return out


def load(stamp: str, *, start_s: float = 0.0, seconds: float = 600.0, values: bool = True) -> dict:
    d = session_dir(stamp)
    j, c = d / "session.json", d / "samples.csv"
    if not j.exists():
        raise DatasetError(f"no session {stamp!r} in {store_root()}")
    meta = json.loads(j.read_text())
    rate = float(meta.get("effective_rate_hz") or meta.get("rate_hz") or 0.0)
    if rate <= 0:
        raise DatasetError(f"session {stamp!r} has no usable rate; it cannot be analysed")
    out = {"meta": meta, "rate_hz": rate, "start_s": start_s, "tags": meta.get("tags") or []}
    if not values or not c.exists():
        return out
    i0 = int(start_s * rate)
    i1 = i0 + int(seconds * rate)
    vals = []
    with open(c) as fh:
        r = csv.reader(fh)
        next(r, None)
        for i, row in enumerate(r):
            if i < i0:
                continue
            if i >= i1:
                break
            try:
                vals.append(float(row[1]))
            except (IndexError, ValueError):
                continue
    out["values"] = vals
    return out


# ------------------------------------------------------------------------------- routing --

VERBS = {"start": start, "append": append, "tag": tag, "stop": stop, "annotate": annotate}


def handle(path: str, body: dict | None = None, query: dict | None = None):
    """Mount point for a consumer's stdlib server. Returns `(payload, status)`.

    One router rather than five, so a session recorded through one host's server is
    byte-identical to one recorded through another's.
    """
    q = query or {}

    def one(k, d):
        return (q.get(k) or [d])[0]

    leaf = path.rstrip("/").rsplit("/", 1)[-1]
    try:
        if body is not None and leaf in VERBS:
            return VERBS[leaf](body), 200
        if leaf == "sessions":
            return {"sessions": catalogue(one("project", None)), "store": str(store_root())}, 200
        if leaf == "session":
            return load(
                one("id", ""),
                start_s=float(one("start", "0")),
                seconds=float(one("seconds", "600")),
                values=one("values", "1") != "0",
            ), 200
        return {"error": f"no dataset route {path!r}"}, 404
    except DatasetError as e:
        return {"error": str(e)}, 400
    except (ValueError, TypeError) as e:
        return {"error": f"{type(e).__name__}: {e}"}, 400
    except OSError as e:
        return {"error": f"dataset unwritable: {e}"}, 503
