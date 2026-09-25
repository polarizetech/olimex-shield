#!/usr/bin/env python3
"""durability.py — a session must never be lost, and a partial one must never look complete.

WHY THIS IS HERE AND NOT IN AN APP
    Ported from an earlier internal project, where this logic (SessionStreamer + FailsafeStore)
    was trapped inside one app and depended on that app's own server routes, so no other client
    of the rig could reach it. The logic was right; the location was wrong. It belongs beside the
    process that OWNS THE SERIAL PORT, because that process is the only one that survives a
    browser crash, a tab close, an HMR restart or a dev-server reload.

THE INVARIANT
    Any code that creates or changes a session type MUST stream the raw timeseries and all derived
    snapshots to disk AS THEY ARE CAPTURED -- never buffered for a single end-of-session write. If
    the app crashes, the session is cancelled, or the operator ends early, the on-disk files must
    contain the maximum possible data up to that instant.

    > A CLEAN-LOOKING EMPTY RECORD IS A WORSE OUTCOME THAN AN EXPLICITLY-FLAGGED PARTIAL ONE.

    That sentence is the whole design. It is why `terminated_early` is written TRUE at init and
    only flipped false by an explicit finalize: every failure mode -- including the ones nobody
    thought of -- leaves a record that is honest about being incomplete.

THE FOUR LAYERS, and what each one survives (see DURABILITY.md for the full table)
    L1  daemon ring buffer + black-box CSV   survives: browser crash, tab close, page reload
    L2  incremental session write (here)     survives: everything L1 does, plus keeps STRUCTURE
    L3  browser IndexedDB failsafe           survives: SERVER death, network loss, this file failing
    L4  beforeunload confirm + sendBeacon    survives: the operator closing the tab by accident

    L3 lives in session-recorder.js because it must survive this process dying. L1 and L2 live
    here because they must survive the browser dying. Neither is redundant with the other; they
    fail in opposite directions, which is the point.

Stdlib only. Writes are atomic (temp + replace) so a kill mid-write cannot corrupt a good record.
"""

import contextlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RECORDINGS = APP_DIR / "recordings"  # gitignored -- physiological data stays local

# Legacy identifier from the bridge's earlier name, kept so existing session files still load.
SCHEMA = "eeg-bridge.session/1"
SAFE = re.compile(r"[^A-Za-z0-9._-]")


class DurabilityError(Exception):
    pass


def _safe(part, what):
    """Path components are sanitised, never joined raw. The browser supplies these."""
    s = SAFE.sub("-", str(part or "")).strip("-.")[:64]
    if not s:
        raise DurabilityError(f"{what} is empty after sanitising; refusing to write")
    return s


def session_dir(app, name):
    return RECORDINGS / _safe(app, "app") / _safe(name, "session name")


def _atomic_write(path, text):
    """Write via temp + os.replace. A crash mid-write leaves the PREVIOUS good file, never a
    half-written one -- which would be the exact 'clean-looking broken record' this module exists
    to prevent, one level down."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ------------------------------------------------------------------ the pre-session self-test --


def disk_selftest(app="_selftest"):
    """CAN THIS PROCESS ACTUALLY WRITE? Run before committing to a long session.

    Not paranoia: a full disk, a bad permission or a read-only mount produces a session that looks
    like it is recording and is not. Discovering that after 60 minutes is the expensive way.
    """
    d = session_dir(app, f"selftest-{int(time.time())}")
    try:
        _atomic_write(d / "probe.json", json.dumps({"ok": True}))
        readback = json.loads((d / "probe.json").read_text())
        (d / "probe.json").unlink()
        d.rmdir()
        free = os.statvfs(str(RECORDINGS if RECORDINGS.exists() else APP_DIR))
        free_mb = free.f_bavail * free.f_frsize / 1e6
        return {
            "ok": readback.get("ok") is True,
            "error": None,
            "root": str(RECORDINGS),
            "free_mb": round(free_mb, 1),
            "warning": (
                "under 200 MB free — a long raw capture may not fit" if free_mb < 200 else None
            ),
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "root": str(RECORDINGS),
            "free_mb": None,
            "warning": "THE SERVER CANNOT WRITE. Recording to disk will fail; only the "
            "in-browser failsafe would capture anything.",
        }


# --------------------------------------------------------------------------- the session writer --


class SessionWriter:
    """Incremental, crash-safe session on disk: one JSON shell plus an append-only raw CSV.

    Lifecycle: init -> update* -> finalize. Every state after init is a VALID, REVIEWABLE record.
    """

    def __init__(self, app, name, csv_header=None, meta=None):
        self.app, self.name = _safe(app, "app"), _safe(name, "session name")
        self.dir = session_dir(app, name)
        self.json_path = self.dir / "session.json"
        self.csv_path = self.dir / "raw.csv"
        self.csv_header = csv_header
        self.meta = meta or {}
        self.rows_written = 0
        # Set when this writer took over a session that was already running (the bridge restarted
        # mid-run). STICKY: it must survive every later update, because the whole point is that the
        # on-disk CSV is INCOMPLETE and the reader has to know.
        self.reattached = False

    # -- the record shell -------------------------------------------------------------------
    def _shell(self, record, terminated_early, phase):
        return {
            "schema": SCHEMA,
            "app": self.app,
            "session": self.name,
            # TRUE FROM INIT. Only finalize() clears it, so any death anywhere leaves it set.
            "terminated_early": terminated_early,
            "phase": phase,
            "started_utc": self.meta.get("started_utc"),
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "raw_csv": self.csv_path.name,
            "raw_rows": self.rows_written,
            "reattached": self.reattached,
            "raw_csv_complete": not self.reattached,
            "reattach_note": (
                "This writer TOOK OVER a session already in progress — the bridge restarted "
                "mid-run. Rows written while it was down are NOT in this CSV; they are in the "
                "browser failsafe. Export it and merge. `raw_rows` is honest but incomplete."
                if self.reattached
                else None
            ),
            # Lets a reviewer tell ELECTRODE DROPOUT (rows present then flat) from a WRITE FAILURE
            # (no rows at all). Those need completely different fixes and look identical in a
            # summary that only reports "session incomplete".
            "has_raw_samples": self.rows_written > 0,
            "meta": self.meta,
            "record": record,
        }

    def init(self, record=None, phase="pre_session", reattached=False):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta.setdefault("started_utc", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        self.reattached = bool(reattached)
        if self.csv_header and not self.csv_path.exists():
            self.csv_path.write_text(self.csv_header.rstrip("\n") + "\n")
        elif reattached and not self.csv_path.exists():
            # A reattach with no header would produce a headerless CSV that looks like a normal
            # one. Say what it is, in the file itself — the file outlives the JSON beside it in
            # every copy-paste and every email.
            self.csv_path.write_text(
                "# REATTACHED after a bridge restart: rows written while the bridge was down are "
                "NOT in this file. Merge the browser failsafe export.\n"
            )
        _atomic_write(self.json_path, json.dumps(self._shell(record, True, phase), indent=1))
        return self.status()

    def update(self, record=None, csv_rows=None, phase=None):
        """Overwrite the JSON with current state and APPEND raw rows. Cheap; call it often."""
        if csv_rows:
            with open(self.csv_path, "a") as fh:
                for row in csv_rows:
                    fh.write((row if isinstance(row, str) else ",".join(map(str, row))) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            self.rows_written += len(csv_rows)
        _atomic_write(self.json_path, json.dumps(self._shell(record, True, phase), indent=1))
        return self.status()

    def finalize(self, record=None, phase="complete", terminated_early=False):
        """The ONLY thing that clears `terminated_early`. Pass True to close out a deliberate abort
        -- an aborted session is still a real record and should be finalised, not abandoned."""
        _atomic_write(
            self.json_path, json.dumps(self._shell(record, terminated_early, phase), indent=1)
        )
        return self.status()

    def status(self):
        return {
            "app": self.app,
            "session": self.name,
            "dir": str(self.dir),
            "json": str(self.json_path),
            "csv": str(self.csv_path),
            "raw_rows": self.rows_written,
            "exists": self.json_path.exists(),
        }


# ------------------------------------------------------------------------- orphan recovery --


def list_orphans(app=None):
    """Sessions that started and never finalised — a crash, a kill, a closed laptop.

    Surfaced rather than cleaned up: the operator decides whether a partial session is usable.
    Deleting it automatically would be this module doing the exact thing it exists to prevent.
    """
    out = []
    root = RECORDINGS / _safe(app, "app") if app else RECORDINGS
    if not root.exists():
        return out
    for js in sorted(root.glob("*/session.json" if app else "*/*/session.json")):
        try:
            rec = json.loads(js.read_text())
        except (OSError, json.JSONDecodeError) as e:
            out.append(
                {
                    "json": str(js),
                    "unreadable": f"{type(e).__name__}: {e}",
                    "terminated_early": True,
                }
            )
            continue
        if rec.get("terminated_early"):
            csv = js.parent / rec.get("raw_csv", "raw.csv")
            out.append(
                {
                    "json": str(js),
                    "app": rec.get("app"),
                    "session": rec.get("session"),
                    "phase": rec.get("phase"),
                    "started_utc": rec.get("started_utc"),
                    "updated_utc": rec.get("updated_utc"),
                    "raw_rows": rec.get("raw_rows", 0),
                    "has_raw_samples": rec.get("has_raw_samples", False),
                    "csv_bytes": csv.stat().st_size if csv.exists() else 0,
                    "terminated_early": True,
                    "diagnosis": (
                        "no raw samples at all — this looks like a WRITE FAILURE or a "
                        "session that died before acquisition started, not electrode dropout"
                        if not rec.get("has_raw_samples")
                        else "raw samples present — the session ran and was interrupted; it is "
                        "reviewable up to the last update"
                    ),
                }
            )
    return out
