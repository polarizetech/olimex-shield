"""storage.py -- hand a finished session to an uploader, if one is configured.

Stdlib only. A session is ALWAYS written to the local store first (`sessions.py`). This module
only passes a finished one to an uploader PLUGIN and keeps a receipt beside it. Uploading itself is
not this repo's job: it is the job of whatever storage tooling the host already has.

    OLIMEX_UPLOADER=none              the default. Sessions stay on this machine.
    OLIMEX_UPLOADER=module:function   `function(session_dir: Path, stamp: str, meta: dict) -> dict`
                                      is called and returns a receipt. `$OLIMEX_UPLOADER_PATH` is
                                      prepended to sys.path first.

An optional companion upload tool provides such a plugin, which writes a hash-pinned PRIVATE
snapshot to S3-compatible object storage and never sets a public ACL. That route was verified
live on 2026-09-15: every object private, every anonymous read 403.
There is deliberately one upload implementation, not two with different manifest formats.

*** WHAT IT REFUSES. ***

  * a session that is still recording, or was never stopped -- a partial upload that looks
    complete is the failure `DURABILITY.md` exists to prevent;
  * a directory with no `session.json` -- that is a folder, not a session;
  * an unknown uploader name, rather than silently treating it as `none` and letting the
    operator believe a copy exists;
  * a plugin that returns anything but a receipt.

The plugin is handed a STAGED copy holding exactly the session's data files. Handing it the live
folder uploaded `uploads.json` -- a receipt from an earlier upload -- into the snapshot (found on
the first live upload), so the same session produced different snapshots depending on its history.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import sessions

RECEIPTS = "uploads.json"  # beside the session, never inside what is uploaded
SCHEMA = "olimex-shield.upload/2"


class StorageError(RuntimeError):
    pass


def uploader_name() -> str:
    return (os.environ.get("OLIMEX_UPLOADER") or "none").strip()


def status() -> dict:
    """What an upload would do right now, without doing it."""
    name = uploader_name()
    if name == "none":
        return {
            "uploader": "none",
            "ready": False,
            "reason": "no uploader configured; sessions stay on this machine "
            "(set OLIMEX_UPLOADER=module:function -- see docs/recording.md)",
        }
    if ":" in name:
        try:
            _plugin(name)
            return {"uploader": name, "ready": True, "reason": None}
        except StorageError as e:
            return {"uploader": name, "ready": False, "reason": str(e)}
    return {
        "uploader": name,
        "ready": False,
        "reason": f"unknown uploader {name!r}; use none or module:function",
    }


def _plugin(spec: str):
    extra = os.environ.get("OLIMEX_UPLOADER_PATH")
    if extra and extra not in sys.path:
        sys.path.insert(0, extra)
    mod, _, fn = spec.partition(":")
    try:
        f = getattr(importlib.import_module(mod), fn)
    except (ImportError, AttributeError) as e:
        raise StorageError(f"uploader plugin {spec!r} could not be loaded: {e}") from e
    if not callable(f):
        raise StorageError(f"uploader plugin {spec!r} is not callable")
    return f


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def data_files(d: Path) -> list[dict]:
    """The session's own files -- what an upload carries. Never the receipts."""
    return [
        {"path": p.relative_to(d).as_posix(), "size": p.stat().st_size, "sha256": _sha256(p)}
        for p in sorted(d.rglob("*"))
        if p.is_file() and p.name != RECEIPTS
    ]


def _finished(stamp: str) -> tuple[Path, dict]:
    d = sessions.session_dir(stamp)
    j = d / "session.json"
    if not j.is_file():
        raise StorageError(f"{stamp!r} has no session.json; it is not a session")
    if stamp in sessions._OPEN:
        raise StorageError(f"{stamp!r} is still recording; stop it before uploading")
    meta = json.loads(j.read_text())
    if meta.get("stopped_at") is None:
        raise StorageError(
            f"{stamp!r} was never stopped (no stopped_at); it may be partial. Nothing was uploaded."
        )
    return d, meta


def upload(stamp: str) -> dict:
    """Pass one FINISHED session to the configured plugin and record a receipt beside it."""
    d, meta = _finished(stamp)
    name = uploader_name()
    if name == "none" or ":" not in name:
        raise StorageError(status()["reason"])
    fn = _plugin(name)
    files = data_files(d)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / stamp
        staged.mkdir()
        for f in files:
            (staged / f["path"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(d / f["path"], staged / f["path"])
        receipt = fn(staged, stamp, meta)
    if not isinstance(receipt, dict):
        raise StorageError(f"uploader {name!r} returned {type(receipt).__name__}, not a receipt")
    receipt = {
        "schema": SCHEMA,
        "uploader": name,
        **receipt,
        "files": receipt.get("files", len(files)),
        "uploaded_at": time.time(),
    }
    rp = d / RECEIPTS
    prior = json.loads(rp.read_text()) if rp.exists() else []
    rp.write_text(json.dumps(prior + [receipt], indent=2, default=str))
    return receipt


def receipts(stamp: str) -> list:
    rp = sessions.session_dir(stamp) / RECEIPTS
    return json.loads(rp.read_text()) if rp.exists() else []
