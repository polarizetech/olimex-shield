#!/usr/bin/env python3
"""serve.py -- the olimex-shield workbench: live view, record, playback, electrode placement.

    python3 apps/web/serve.py            # http://127.0.0.1:8150/
    python3 apps/web/serve.py 8150 --no-bridge --bridge http://127.0.0.1:8140

WHAT IT IS AND IS NOT
    It is static files, a JSON API and a PROXY. It never opens the serial port: `apps/server`
    (the bridge) owns it, because only one process may hold a serial device and the bridge is
    what survives a closed tab. `/bridge/*` forwards to the bridge, including a line-by-line
    pipe for the SSE stream -- `urlopen().read()` never returns on an event stream.

    If no bridge answers at start-up, this starts one bound to 127.0.0.1 and stops it on exit.
    `--no-bridge` turns that off (for a bridge you run yourself, or elsewhere).

ROUTES
    GET  /                          the workbench
    GET  /design/*                  vendored design system (vendor/design, synced, never edited)
    GET  /signal-panel/*            <signal-panel> and <signal-panel-atlas>
    *    /bridge/*                  the bridge
    GET  /api/readouts              EEG / ECG / EMG and whether this board can carry each
    GET  /api/gate?readout=         the front-end verdict for one readout
    GET  /api/hookup?readout=       placement diagram, sites, prep and the FULL safety list
    GET  /api/sessions              every recorded session
    GET  /api/session?id=&start=&seconds=&values=
    POST /dataset/{start,append,tag,stop,annotate}   the session store (what Record writes through)
    GET  /api/tools                 which optional companion tools (atlas, detection) are present
    GET  /api/storage               the configured uploader and whether it is ready
    POST /api/upload {stamp}        copy a finished session to the configured PRIVATE target
    POST /api/export/bids {stamp, subject, task, session?}

STDLIB ONLY. A recording must not be able to fail because a library moved.

THE SESSION DATA IS READABLE BY ANYONE WHO CAN REACH THIS PORT. It binds 127.0.0.1 by default
for exactly that reason; `--bind 0.0.0.0` is a decision, and the start-up line says so.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

APP_DIR = Path(__file__).resolve().parent
REPO = APP_DIR.parents[1]
SERVER_DIR = REPO / "apps" / "server"
DESIGN_DIR = APP_DIR / "vendor" / "design"
PANEL_DIR = APP_DIR / "signal-panel"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(SERVER_DIR))

import bids  # noqa: E402
import hookup  # noqa: E402
import readouts  # noqa: E402
import sessions  # noqa: E402
import storage  # noqa: E402

DEFAULT_PORT = 8150


def tools_dir():
    """The directory holding the optional companion analysis tools: $OLIMEX_TOOLS, else the
    nearest parent with a REGISTRY.md. The Atlas tab and the extraction widgets come from there;
    without it they are switched off."""
    env = os.environ.get("OLIMEX_TOOLS")
    if env:
        return Path(env) if Path(env).is_dir() else None
    for up in REPO.parents:
        if (up / "REGISTRY.md").is_file():
            return up
    return None


def optional_tools() -> dict:
    t = tools_dir()
    atlas = t / "auditory-atlas" / "atlas-panel.js" if t else None
    return {
        "tools_dir": str(t) if t else None,
        "atlas": bool(atlas and atlas.is_file()),
        "detection": bool(t and (t / "signal-detection" / "extract.py").is_file()),
        "note": None
        if t
        else (
            "the Atlas tab and the extraction widgets come from optional companion "
            "analysis tools, which are not installed here (set OLIMEX_TOOLS)"
        ),
    }


BRIDGE = os.environ.get("OLIMEX_BRIDGE", "http://127.0.0.1:8140")
EXPORT_ROOT = Path(os.environ.get("OLIMEX_EXPORTS") or REPO / "exports" / "bids")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(APP_DIR), **kw)

    def log_message(self, fmt, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        parts = [p for p in clean.split("/") if p]
        # Source, vendored internals and anything dotted are not served.
        if clean.endswith(".py") or any(p.startswith(".") or p in ("__pycache__",) for p in parts):
            return "/dev/null/blocked"
        if parts == ["signal-panel", "atlas-panel.js"]:
            t = tools_dir()
            return str(t / "auditory-atlas" / "atlas-panel.js") if t else "/dev/null/blocked"
        if parts[:1] == ["design"]:
            return str(DESIGN_DIR.joinpath(*parts[1:]))
        if parts[:1] == ["vendor"] or parts[:1] == ["placement"]:
            return "/dev/null/blocked"
        return super().translate_path(path)

    # ------------------------------------------------------------------------- helpers --
    def _json(self, obj, code=200):
        body = json.dumps(obj, allow_nan=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _query(self):
        q = parse_qs(urlsplit(self.path).query)
        return q, (lambda k, d=None: (q.get(k) or [d])[0])

    def _bridge_down(self, e):
        return {
            "error": f"bridge unreachable at {BRIDGE}: {e}",
            "hint": "python3 apps/server/serve.py 8140 127.0.0.1",
            "note": "The bridge owns the serial port. The workbench never opens it.",
        }

    def _proxy(self, path, body=None):
        req = urllib.request.Request(
            BRIDGE + path[len("/bridge") :],
            data=(json.dumps(body).encode() if body is not None else None),
            headers={"Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                self._json(json.loads(r.read() or b"{}"), r.status)
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                self._json(json.loads(raw), e.code)
            except ValueError:
                self._json({"error": raw, "status": e.code}, e.code)
        except Exception as e:
            self._json(self._bridge_down(e), 503)

    def _proxy_stream(self, path):
        try:
            r = urllib.request.urlopen(BRIDGE + path[len("/bridge") :], timeout=20)
        except Exception as e:
            return self._json(self._bridge_down(e), 503)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for line in r:
                self.wfile.write(line)
                if line in (b"\n", b"\r\n"):
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            r.close()

    # -------------------------------------------------------------------------- routes --
    def do_GET(self):
        p = self.path.split("?", 1)[0].rstrip("/") or "/"
        q, one = self._query()
        if p.startswith("/bridge"):
            full = self.path
            return self._proxy_stream(full) if p == "/bridge/stream" else self._proxy(full)
        try:
            if p == "/api/readouts":
                return self._json(
                    {
                        "readouts": readouts.catalogue(),
                        "refused": {k: v["reasons"] for k, v in readouts.REFUSED.items()},
                    }
                )
            if p == "/api/gate":
                return self._json(readouts.gate(one("readout", "eeg")))
            if p == "/api/hookup":
                return self._json(hookup.guide(one("readout", "eeg")))
            if p == "/api/tools":
                return self._json(optional_tools())
            if p == "/api/storage":
                return self._json(
                    {
                        **storage.status(),
                        "store": str(sessions.store_root()),
                        "exports": str(EXPORT_ROOT),
                    }
                )
            if p in ("/api/sessions", "/api/session"):
                payload, code = sessions.handle(p, None, q)
                if p == "/api/sessions" and code == 200:
                    for s in payload["sessions"]:
                        s["uploads"] = len(storage.receipts(s["stamp"]))
                return self._json(payload, code)
        except (readouts.ReadoutError, sessions.DatasetError, ValueError) as e:
            # A guide that cannot be built is a 400 WITH the reason, never a partial guide.
            return self._json({"error": f"{type(e).__name__}: {e}"}, 400)
        return super().do_GET()

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        try:
            body = self._body()
        except ValueError as e:
            return self._json({"error": f"bad JSON: {e}"}, 400)
        if p.startswith("/bridge/"):
            return self._proxy(p, body)
        if p.startswith("/dataset/"):
            payload, code = sessions.handle(p, body)
            return self._json(payload, code)
        try:
            if p == "/api/upload":
                return self._json(storage.upload(body.get("stamp")))
            if p == "/api/export/bids":
                return self._json(
                    bids.export(
                        body.get("stamp"),
                        EXPORT_ROOT,
                        subject=body.get("subject") or "01",
                        session=body.get("session") or None,
                        task=body.get("task") or "rest",
                        allow_synthetic=bool(body.get("allow_synthetic")),
                    )
                )
        except (storage.StorageError, bids.ExportError, sessions.DatasetError) as e:
            return self._json({"error": str(e)}, 400)
        except Exception as e:  # an upload's network failure, say
            return self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        return self._json({"error": f"no route {p}"}, 404)


def bridge_up(url: str = BRIDGE) -> bool:
    try:
        with urllib.request.urlopen(url + "/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_bridge(url: str = BRIDGE) -> subprocess.Popen | None:
    port = urlsplit(url).port or 8140
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_DIR / "serve.py"), str(port), "127.0.0.1"], cwd=str(SERVER_DIR)
    )
    atexit.register(lambda: proc.poll() is None and proc.terminate())
    return proc


def main(argv=None):
    global BRIDGE
    ap = argparse.ArgumentParser(description="olimex-shield workbench")
    ap.add_argument("port", nargs="?", type=int, default=8150)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--bridge", default=BRIDGE)
    ap.add_argument(
        "--no-bridge", action="store_true", help="do not start a bridge if none answers"
    )
    a = ap.parse_args(argv)
    BRIDGE = a.bridge.rstrip("/")
    if not bridge_up(BRIDGE):
        if a.no_bridge:
            print(f"  ! no bridge at {BRIDGE}; live view will say so until one is running")
        else:
            start_bridge(BRIDGE)
            print(f"  started a bridge at {BRIDGE} (bound to 127.0.0.1)")
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print(f"olimex-shield workbench on http://{a.bind}:{a.port}/   bridge {BRIDGE}")
    print(f"  sessions -> {sessions.store_root()}   uploader: {storage.status()['uploader']}")
    if a.bind not in ("127.0.0.1", "localhost"):
        print("  ! bound beyond localhost: anyone who can reach this port can read every session")
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()


if __name__ == "__main__":
    main()
