#!/usr/bin/env python3
"""
The olimex-shield bridge — the one process that holds the board's serial port.

(Analysis that is not this board's job -- the Auditory Response Atlas, the extraction layer --
lives in optional companion analysis tools. Their routes are served here when those tools are
present, and answer 503 "not installed" when they are not.)

WHY THIS EXISTS
    Only ONE process on the machine may hold the serial port. This service owns the device, and
    every app is a thin client over HTTP/SSE (CORS is enabled precisely so apps on other ports can
    consume it), so a second consumer never has to fight for the port or duplicate the reader.

WHAT IT TALKS TO
    An Arduino running the Olimex SHIELD-EKG-EMG (or any board emitting CSV lines over serial).
    Line format: "t_us,ch0,ch1,..." -- one sample per line. `channel_col` selects the column
    (default 1 = ch0). Default 115200 baud, ~250 Hz sample rate.

DESIGN
    - The SERVER owns the port, not the browser. A browser reload kills a Web Serial read loop and
      takes the acquisition with it; here the reader thread survives, and a reattaching client just
      resumes from its last sample index. Acquisition never stops.
    - A ring buffer with a MONOTONIC total counter, so a client that falls behind can detect the
      gap.
    - `open` is idempotent (same port+baud already running -> no-op), so a reload must not reset the
      device.
    - A server-side "black box" recorder: when armed, every sample hits disk independent of any
      browser, so a tab/OS crash mid-session still leaves a complete raw capture.

RUN
    python3 serve.py [PORT] [BIND]        # default 8140 127.0.0.1; 0.0.0.0 exposes the stream
    pip install pyserial                  # optional; without it the service still runs and reports
                                          # supported:false so clients can fall back to Web Serial.
"""

import contextlib
import glob
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# This board's own trust tooling: stdlib, always present. timebase is not behind the tools guard:
# measuring the rate the board actually delivers is part of acquisition, not analysis.
import durability
import quality
import timebase

try:
    # pyserial lets this service OWN the port, so acquisition survives browser reloads.
    import serial

    _HAVE_PYSERIAL = True
except Exception:
    _HAVE_PYSERIAL = False

# ------------------------------------------------------------------- experimental analysis --
# The lock-in / extraction / integration-check / noise-budget / detection-curve / rate-trade /
# atlas routes are EXPERIMENTAL and depend on optional companion tools. All of it lives in
# experimental.py, imported here inside a guard: acquisition never depends on it, because
# acquisition is the job that cannot be allowed to fail.
try:
    import experimental

    _HAVE_ATLAS, _ATLAS_ERROR = experimental._HAVE_ATLAS, experimental._ATLAS_ERROR
    _HAVE_DETECTION, _DETECTION_ERROR = experimental._HAVE_DETECTION, experimental._DETECTION_ERROR
    TOOLS_DIR = experimental.TOOLS_DIR
    _EXP_FIREWALL = experimental.FIREWALL_ERRORS
except Exception as _e:  # pragma: no cover - import guard
    experimental = None
    _HAVE_ATLAS = _HAVE_DETECTION = False
    _ATLAS_ERROR = _DETECTION_ERROR = f"experimental.py failed to import: {_e}"
    TOOLS_DIR = None
    _EXP_FIREWALL = ()


class _Missing:
    """Stands in for anything absent, so an `except x.DomainError` clause can never itself
    NameError while handling an error -- the worst failure mode for the acquisition service."""

    class DomainError(ValueError):
        pass

    class ModalityError(TypeError):
        pass


def _missing(what, err):
    if experimental is not None:
        return experimental._missing(what, err)
    return {"error": f"{what} is not installed here", "detail": err, "experimental": True}


_FIREWALL_ERRORS = tuple(set(_EXP_FIREWALL) | {quality.DomainError})

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
REC_DIR = os.path.join(APP_ROOT, "recordings")  # self-contained; gitignored
DEFAULT_RATE = 250  # Hz, nominal — clients may measure the real rate

# This process serves no front end and therefore no design assets: the UI is the workbench's
# <signal-panel> (apps/web/signal-panel). If a backend-only need for a design asset shows up,
# add an explicit allow-list entry rather than a directory mount or a fallback default.
STATIC = {
    # This process owns the device and the backend routes only, never the front end.
    "/eeg-client.js": ("eeg-client.js", "application/javascript"),
    # Shared for the same reason eeg-client.js is: every rig consumer gets ONE durability layer,
    # so a fix to the failsafe reaches every app instead of one. See DURABILITY.md.
    "/session-recorder.js": ("session-recorder.js", "application/javascript"),
}


def parse_line(line, channel_col=1):
    """One CSV line from the board -> (t_us, value), None for a blank/comment line, or False for a
    malformed one.

    Parsed POSITIONALLY: column 0 is `t_us`, `channel_col` the value. The old parser skipped
    non-numeric tokens and so shifted every later column left -- a garbled `t_us` turned ch1 into
    ch0 silently. With `channel_col == 0` there is no `t_us` column and t_us is None.
    """
    t = line.strip()
    if not t or t.startswith("#"):
        return None
    toks = [x for x in re.split(r"[,\s]+", t) if x]
    if len(toks) <= channel_col:
        return False
    try:
        v = float(toks[channel_col])
        t_us = None if channel_col == 0 else int(float(toks[0]))
    except ValueError:
        return False
    if v != v or v in (float("inf"), float("-inf")):
        return False
    return t_us, v


def _new_rec_counts():
    return {
        "samples_timed": 0,
        "parse_errors": 0,
        "gaps": 0,
        "max_gap_us": 0,
        "short_steps": 0,
        "clock_resets": 0,
    }


def read_black_box(path):
    """Read a black-box recording, old (`sample_index,value`) or new (`...,t_us`).

    Returns {"header": [comment lines], "columns": [...], "rows": [(index, value, t_us|None)]}.
    """
    header, rows, columns = [], [], None
    with open(path) as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                header.append(line)
                continue
            parts = line.split(",")
            if columns is None:
                columns = parts
                continue
            t_us = int(parts[2]) if len(parts) > 2 and parts[2] != "" else None
            rows.append((int(parts[0]), float(parts[1]), t_us))
    return {"header": header, "columns": columns or [], "rows": rows}


class SerialDaemon:
    """Owns the port. Reads CSV lines into a ring with a monotonic sample counter."""

    RING = DEFAULT_RATE * 60  # ~60 s of catch-up for a reattaching client

    def __init__(self):
        self.lock = threading.Lock()
        self.port = None
        self.port_name = None
        self.baud = None
        self.channel_col = 1
        self.buf = []
        self.total = 0  # monotonic count of ALL samples ever read (survives ring trim)
        self.generation = 0  # bumps on each (re)open so a client can detect a device swap
        self.last_ms = 0.0
        self.running = False
        self.error = None
        self._thread = None
        # The rate actually delivered, against the host clock. Reset with the counter on every
        # (re)open, because a new port is a new clock.
        self.rate_est = timebase.RateEstimator(DEFAULT_RATE)
        # What the wire lost, from the board's own t_us: parse failures and gaps. Reset on every
        # (re)open with the counter. Nothing here ever inserts a sample.
        self.integrity = timebase.StreamIntegrity(DEFAULT_RATE)
        self._rec_counts = None  # per-recording integrity counters while the black box is armed
        self.rec_lock = threading.Lock()
        self.rec_file = None
        self.rec_path = None
        self.rec_written = 0
        self.rec_error = None
        self._rec_last_fsync = 0.0

    def list_ports(self):
        pats = [
            "/dev/cu.usbmodem*",
            "/dev/cu.usbserial*",
            "/dev/cu.usb*",
            "/dev/tty.usbmodem*",
            "/dev/tty.usbserial*",
        ]
        found = set()
        for p in pats:
            found.update(glob.glob(p))
        # macOS exposes each device as BOTH /dev/cu.* (callout — the one to use) and /dev/tty.*
        # (dial-in). Collapse the pair so one device isn't offered twice.
        cu_suffixes = {p[len("/dev/cu.") :] for p in found if p.startswith("/dev/cu.")}
        out = [
            p for p in found if p.startswith("/dev/cu.") or p[len("/dev/tty.") :] not in cu_suffixes
        ]
        return sorted(out)

    # A synthetic source, so the UI and every analysis path can be exercised with no hardware
    # attached. It is a SEPARATE port name rather than a silent fallback, and `status()` reports
    # `demo: true` for as long as it runs, because the one unforgivable failure here would be
    # someone mistaking generated data for a recording. Nothing downstream special-cases it: the
    # samples go through the same ring, the same SSE stream and the same recorder.
    DEMO_PORT = "demo://synthetic"

    def open(self, port_name, baud=115200, channel_col=1):
        if port_name == self.DEMO_PORT:
            return self._open_demo()
        if not _HAVE_PYSERIAL:
            raise RuntimeError("pyserial not installed — pip install pyserial")
        with self.lock:
            if (
                self.running
                and self.port_name == port_name
                and self.baud == baud
                and self.error is None
            ):
                return self._status_locked()  # idempotent: a reload must NOT reopen/reset
        self.close()
        handle = serial.Serial(port_name, baud, timeout=0.1)
        with self.lock:
            self.port = handle
            self.port_name, self.baud = port_name, baud
            self.channel_col = int(channel_col)
            self.buf, self.total = [], 0
            self.rate_est.reset()
            self.integrity.reset()
            self.generation += 1
            self.last_ms = time.time() * 1000.0
            self.error = None
            self.running = True
            gen = self.generation
        self._thread = threading.Thread(target=self._reader, args=(gen,), daemon=True)
        self._thread.start()
        return self.status()

    def close(self):
        with self.lock:
            self.running = False
            h, self.port = self.port, None
        if h is not None:
            with contextlib.suppress(Exception):
                h.close()

    def _open_demo(self):
        with self.lock:
            if self.running and self.port_name == self.DEMO_PORT:
                return self._status_locked()
        self.close()
        with self.lock:
            self.port = "demo"  # truthy, so `open` reads true in status
            self.port_name, self.baud = self.DEMO_PORT, 0
            self.channel_col = 1
            self.buf, self.total = [], 0
            self.rate_est.reset()
            self.integrity.reset()
            self.generation += 1
            self.last_ms = time.time() * 1000.0
            self.error = None
            self.running = True
            gen = self.generation
        self._thread = threading.Thread(target=self._demo_reader, args=(gen,), daemon=True)
        self._thread.start()
        return self.status()

    def _demo_reader(self, gen):
        """Plausible EEG in ADC counts: an alpha burst that waxes and wanes, 1/f background, mains,
        and the occasional blink. Deliberately NOT a clean sinusoid — a demo that looks better than
        real data teaches the wrong expectation about what a good channel looks like."""
        import math as _m
        import random as _rnd

        rng = _rnd.Random(7)
        k = 0
        pink = 0.0
        period = 1.0 / DEFAULT_RATE
        next_t = time.time()
        while True:
            with self.lock:
                if not self.running or self.generation != gen:
                    return
            vals, tus = [], []
            for _ in range(10):  # ~25 Hz of 10-sample chunks
                t = k * period
                # A synthetic board clock, stepping exactly one period: the demo exercises the same
                # integrity path as a real port and, correctly, never reports a gap.
                tus.append(int(round(t * 1e6)) % timebase.T_US_MODULUS)
                pink = 0.97 * pink + rng.gauss(0, 6.0)  # drifting 1/f-ish background
                alpha_env = 0.5 + 0.5 * _m.sin(2 * _m.pi * 0.07 * t)
                v = (
                    512.0
                    + pink
                    + 14.0 * alpha_env * _m.sin(2 * _m.pi * 10.2 * t)
                    + 2.0 * _m.sin(2 * _m.pi * 60.0 * t)  # mains, small but present
                    + rng.gauss(0, 3.0)
                )
                if rng.random() < 0.0006:
                    self._blink = 40  # a blink: big, slow, unmistakable
                if getattr(self, "_blink", 0) > 0:
                    v += 90.0 * (self._blink / 40.0)
                    self._blink -= 1
                vals.append(v)
                k += 1
            with self.lock:
                if not self.running or self.generation != gen:
                    return
                for tu in tus:
                    self._count_step(self.integrity.add(tu))
                self.buf.extend(vals)
                self.total += len(vals)
                base_idx = self.total - len(vals)
                if len(self.buf) > self.RING:
                    del self.buf[: len(self.buf) - self.RING]
                self.last_ms = time.time() * 1000.0
                # Measured like a real port, so the demo exercises the same path. It is paced by the
                # host clock, so it should read ~0 ppm -- which is itself a check on the estimator.
                self.rate_est.add(time.monotonic(), self.total)
            self._record(base_idx, vals, tus)
            next_t += 10 * period
            time.sleep(max(0.0, next_t - time.time()))

    def _reader(self, gen):
        carry = ""
        first_chunk = True
        while True:
            with self.lock:
                if not self.running or self.generation != gen or self.port is None:
                    return
                h = self.port
            try:
                data = h.read(512)
            except Exception as e:
                with self.lock:
                    self.error, self.running = str(e), False
                return
            # Taken the moment the bytes are in hand, before any parsing, so parse time never counts
            # as latency. Every complete line in this chunk arrived no later than this instant.
            arrived = time.monotonic()
            if not data:
                continue
            carry += data.decode("ascii", "ignore")
            lines = carry.split("\n")
            carry = lines.pop()
            if first_chunk and lines:
                # The port was opened mid-stream: the first line is (usually) the tail of one the
                # board was already sending. It was never ours, so it is neither a sample nor an
                # error.
                first_chunk = False
                lines.pop(0)
            vals, tus = [], []
            errors = 0
            for line in lines:
                parsed = parse_line(line, self.channel_col)
                if parsed is None:
                    continue  # blank or a `#` comment
                if parsed is False:
                    errors += 1  # malformed: dropped and COUNTED, never replaced
                    continue
                t_us, v = parsed
                vals.append(v)
                tus.append(t_us)
            if vals or errors:
                with self.lock:
                    for _ in range(errors):
                        self.integrity.parse_error()
                        if self._rec_counts is not None:
                            self._rec_counts["parse_errors"] += 1
                    for tu in tus:
                        if tu is not None:
                            self._count_step(self.integrity.add(tu))
                    if not vals:
                        continue
                    self.buf.extend(vals)
                    self.total += len(vals)
                    base_idx = self.total - len(vals)
                    if len(self.buf) > self.RING:
                        del self.buf[: len(self.buf) - self.RING]
                    self.last_ms = time.time() * 1000.0
                    self.rate_est.add(arrived, self.total)
                self._record(base_idx, vals, tus)  # disk I/O OUTSIDE the buf lock — never stall SSE

    def _count_step(self, step):
        """Mirror one integrity step into the armed recording's own counters. Caller holds lock."""
        rc = self._rec_counts
        if rc is None:
            return
        kind, dt = step
        if kind is None:
            return
        rc["samples_timed"] += 1
        if kind == "gap":
            rc["gaps"] += 1
            rc["max_gap_us"] = max(rc["max_gap_us"], dt)
        elif kind == "short":
            rc["short_steps"] += 1
        elif kind == "reset":
            rc["clock_resets"] += 1

    def _record(self, base_idx, vals, tus=None):
        with self.rec_lock:
            f = self.rec_file
            if f is None:
                return
            try:
                ts = tus if tus is not None else [None] * len(vals)
                f.write(
                    "".join(
                        f"{base_idx + i},{v},{'' if t is None else t}\n"
                        for i, (v, t) in enumerate(zip(vals, ts))
                    )
                )
                f.flush()
                self.rec_written += len(vals)
                now = time.time()
                if now - self._rec_last_fsync >= 3.0:
                    os.fsync(f.fileno())
                    self._rec_last_fsync = now
            except Exception as e:
                self.rec_error = str(e)

    def start_record(self, name):
        os.makedirs(REC_DIR, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name or "capture")
        path = os.path.join(REC_DIR, f"{safe}.csv")
        with self.rec_lock:
            if self.rec_file is not None and self.rec_path == path:
                return {"recording": True, "recPath": path, "recWritten": self.rec_written}
            if self.rec_file is not None:
                with contextlib.suppress(Exception):
                    self.rec_file.close()
            # Held open across calls and closed by stop_record(), so not a `with` block.
            f = open(path, "w")  # noqa: SIM115
            # "# eeg-bridge" is a legacy header identifier, kept so older readers still parse it.
            f.write(
                f"# eeg-bridge port={self.port_name} baud={self.baud} "
                f"channel_col={self.channel_col} started_total={self.total}\n"
            )
            # t_us is the board's own clock for that sample (empty when the line had none). Older
            # recordings have only `sample_index,value`; read_black_box() reads both.
            f.write("sample_index,value,t_us\n")
            self.rec_file, self.rec_path = f, path
            self.rec_written, self.rec_error = 0, None
            self.rec_start_total = self.total
        with self.lock:
            self._rec_counts = _new_rec_counts()
        return {"recording": True, "recPath": path, "recWritten": 0}

    def stop_record(self):
        with self.lock:
            counts, self._rec_counts = self._rec_counts, None
        with self.rec_lock:
            f, self.rec_file = self.rec_file, None
            path, written = self.rec_path, self.rec_written
            self.rec_path = None
        counts = counts or _new_rec_counts()
        if f is not None:
            try:
                # A trailing comment, so the file itself says what the wire lost while it was armed.
                f.write(
                    f"# stopped written={written} parse_errors={counts['parse_errors']} "
                    f"gaps={counts['gaps']} max_gap_us={counts['max_gap_us']} "
                    f"clock_resets={counts['clock_resets']}\n"
                )
                f.flush()
                os.fsync(f.fileno())
                f.close()
            except Exception:
                pass
        return {
            "recording": False,
            "recPath": path,
            "recWritten": written,
            # What the wire lost WHILE this recording was armed (not since the port opened).
            "recParseErrors": counts["parse_errors"],
            "recGaps": counts["gaps"],
            "recMaxGapUs": counts["max_gap_us"],
            "recIntegrity": counts,
        }

    def read_since(self, cur):
        """Samples the client hasn't seen → (samples, new_total, actual_from). If the client is
        further behind than the ring retains, actual_from jumps forward — a gap the client can
        flag."""
        with self.lock:
            if cur > self.total:
                cur = self.total
            avail = self.total - cur
            if avail <= 0:
                return [], self.total, self.total
            if avail > len(self.buf):
                cur = self.total - len(self.buf)
            start = len(self.buf) - (self.total - cur)
            return self.buf[start:], self.total, cur

    def _status_locked(self):
        since = (time.time() * 1000.0 - self.last_ms) if self.last_ms else None
        rt = self.rate_est.estimate()
        return {
            "supported": _HAVE_PYSERIAL,
            "open": bool(self.running and self.port is not None),
            "port": self.port_name,
            "baud": self.baud,
            "channelCol": self.channel_col,
            "demo": self.port_name == self.DEMO_PORT,
            "demoWarning": (
                "SYNTHETIC DATA — generated by this service, not recorded from anyone. "
                "Nothing measured here is evidence of anything."
                if self.port_name == self.DEMO_PORT
                else None
            ),
            # `rate` stays the DECLARED rate: consumers size rings and clocks with it, and a value
            # that moves mid-session would move every tag. It is NOT a measurement -- until
            # 2026-09-15 consumers called it one. The measured rate is beside it, or null with the
            # reason, and anything doing lock-in detection should use that.
            "rate": DEFAULT_RATE,
            "rateDeclared": rt["declared_hz"],
            "rateMeasured": rt["measured_hz"],
            "rateErrorPpm": rt["error_ppm"],
            "rateUncertaintyPpm": rt["uncertainty_ppm"],
            "rateBasis": rt["basis"],
            "total": self.total,
            "generation": self.generation,
            # What the wire lost since this port was opened, from the board's own t_us. Flat
            # aliases for the three numbers a client most needs; the full record under `stream`.
            "parseErrors": self.integrity.parse_errors,
            "streamGaps": self.integrity.gaps,
            "maxGapUs": self.integrity.max_gap_us,
            "stream": self.integrity.snapshot(),
            "sinceLastSampleMs": round(since) if since is not None else None,
            "error": self.error,
            "recording": self.rec_file is not None,
            "recPath": self.rec_path,
            "recWritten": self.rec_written,
            "recError": self.rec_error,
        }

    def status(self):
        with self.lock:
            return self._status_locked()


DAEMON = SerialDaemon()


def _rate_for(body):
    """(rate, basis) for an analysis request.

    A caller that states `rate` owns it -- they supplied the samples and know where they came from.
    For the daemon's OWN ring (`source: "live"`) this process knows better than its constant: the
    measured rate is used once it exists, because at -644 ppm a lock-in at a nominal frequency nulls
    a 40 dB line within 40 s (RIG.md, 2026-09-15). Until it exists, the declared rate, labelled so.
    """
    if body.get("rate") is not None:
        return float(body["rate"]), "caller"
    if body.get("source") == "live":
        st = DAEMON.status()
        if st.get("rateMeasured"):
            return float(st["rateMeasured"]), "measured"
        return float(DEFAULT_RATE), "declared (not yet measured)"
    return float(DEFAULT_RATE), "declared"


def _samples_for(body):
    """Samples for an extraction request: supplied outright, or the tail of the daemon's ring.

    The live path is why this service is the right home for the extraction layer at all — the
    process that already owns the port can answer 'is the response there yet' without anyone
    exporting a file. Note the direction: this reads the daemon. The daemon does not read this.
    """
    if body.get("samples"):
        return [float(v) for v in body["samples"]]
    if body.get("source") == "live":
        rate, _basis = _rate_for(body)
        want = int(round(float(body.get("seconds", 10.0)) * rate))
        st = DAEMON.status()
        total = st.get("total", 0)
        if total < want:
            raise ValueError(
                f"only {total} samples acquired so far; {want} requested. "
                "Acquisition has not run long enough for this dwell."
            )
        # `read_since` returns THREE values -- (samples, new_total, actual_from) -- and this
        # unpacked two, so every `source: "live"` request raised
        # `too many values to unpack (expected 2, got 3)` and came back 400. That is the whole
        # live path of the extraction layer: /quality, /bands, /spectrum, /integration-check
        # and every /extract* route. Found the first time a client asked a real
        # attached rig whether the electrodes were on anything.
        #
        # It survived because nothing tested it: the synthetic suites all pass `samples`
        # outright, and the SSE handler -- the only other caller -- unpacks three correctly.
        vals, _total, _actual_from = DAEMON.read_since(max(0, total - want))
        return [float(v) for v in vals]
    raise ValueError('no samples: pass `samples` or `source:"live"` with `seconds`')


_LOOPBACK_ORIGIN = re.compile(r"^http://(127\.0\.0\.1|localhost|\[::1\])(:\d{1,5})?$")


def origin_allowed(origin):
    """True for http://127.0.0.1:<port>, http://localhost:<port>, http://[::1]:<port>, or an exact
    entry in the comma-separated $OLIMEX_ALLOWED_ORIGINS."""
    origin = (origin or "").strip().rstrip("/")
    if not origin:
        return False
    if _LOOPBACK_ORIGIN.match(origin):
        return True
    extra = os.environ.get("OLIMEX_ALLOWED_ORIGINS", "")
    return origin in {o.strip().rstrip("/") for o in extra.split(",") if o.strip()}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    # CORS: other apps on other LOCAL ports must be able to call this, but a random web page the
    # operator happens to have open must not be able to read their physiology. So the Origin is
    # echoed only when it is loopback (any port) or listed in $OLIMEX_ALLOWED_ORIGINS; `*` is gone.
    def _cors(self):
        origin = self.headers.get("Origin") if self.headers else None
        if origin and origin_allowed(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _q(self):
        if "?" not in self.path:
            return {}
        out = {}
        for kv in self.path.split("?", 1)[1].split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                out[k] = v
        return out

    # Session writers are held per (app, name) so `update` appends to the same open session
    # instead of restarting it. Bounded: a stale entry is a dict, not a file handle.
    _SESSIONS = {}

    def _session_op(self, path, body):
        app, name = body.get("app"), body.get("name")
        if not app or not name:
            return self._json(400, {"error": "session ops need both `app` and `name`"})
        key = (str(app), str(name))
        try:
            if path == "/session/init":
                w = durability.SessionWriter(
                    app, name, csv_header=body.get("csv_header"), meta=body.get("meta") or {}
                )
                self.__class__._SESSIONS[key] = w
                return self._json(
                    200, w.init(body.get("record"), phase=body.get("phase", "pre_session"))
                )
            w = self.__class__._SESSIONS.get(key)
            if w is None:
                # A restarted bridge lost the handle. Re-attach rather than refuse: refusing here
                # would lose the rest of a session that is still running, which is the one outcome
                # this module exists to prevent.
                w = durability.SessionWriter(
                    app, name, csv_header=body.get("csv_header"), meta=body.get("meta") or {}
                )
                w.init(body.get("record"), phase=body.get("phase", "reattached"), reattached=True)
                self.__class__._SESSIONS[key] = w
            if path == "/session/update":
                return self._json(
                    200, w.update(body.get("record"), body.get("csv_rows"), phase=body.get("phase"))
                )
            out = w.finalize(
                body.get("record"),
                phase=body.get("phase", "complete"),
                terminated_early=bool(body.get("terminated_early")),
            )
            self.__class__._SESSIONS.pop(key, None)
            return self._json(200, out)
        except durability.DurabilityError as e:
            return self._json(400, {"error": str(e)})
        except OSError as e:
            return self._json(
                500,
                {
                    "error": f"disk write failed: {e}",
                    "hint": "the in-browser failsafe is still capturing",
                },
            )

    def _file(self, disk_path, ctype):
        try:
            with open(disk_path, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._json(404, {"error": f"{os.path.basename(disk_path)} missing"})
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path in ("/", "/health"):
            return self._json(
                200,
                {
                    "service": "olimex-shield bridge",
                    "pyserial": _HAVE_PYSERIAL,
                    "atlas": _HAVE_ATLAS,
                    "atlasError": _ATLAS_ERROR,
                    "detection": _HAVE_DETECTION,
                    "detectionError": _DETECTION_ERROR,
                    "toolsDir": TOOLS_DIR,
                    "acquisition": [
                        "/status",
                        "/ports",
                        "/open",
                        "/close",
                        "/stream?from=N",
                        "/record",
                        "/record/stop",
                    ],
                    "atlasEndpoints": [
                        "/atlas/reference",
                        "/claims",
                        "POST /predict",
                        "POST /montage",
                        "POST /simulate",
                    ],
                    "session": ["POST /quality", "POST /bands", "POST /spectrum"],
                    # Everything below this line is EXPERIMENTAL (experimental.py) and needs the
                    # optional companion tools; see docs/experimental.md.
                    "experimental": list(experimental.ROUTES) if experimental else [],
                    "ui": (
                        "apps/web (the workbench) -- <signal-panel> + optional <signal-panel-atlas>"
                    ),
                    "extraction": [
                        "POST /extract",
                        "POST /extract/sustain",
                        "POST /extract/artifact",
                        "POST /extract/feasibility",
                        "POST /integration-check",
                        "POST /noise-budget",
                        "POST /detection-curve",
                        "POST /rate-trade",
                        "GET /extract/reference",
                    ],
                },
            )
        if path == "/status":
            return self._json(200, DAEMON.status())
        if path == "/ports":
            return self._json(
                200,
                {
                    "supported": _HAVE_PYSERIAL,
                    "ports": DAEMON.list_ports(),
                    "demoPort": SerialDaemon.DEMO_PORT,
                },
            )
        if path == "/stream":
            return self._stream()

        if path in STATIC:
            name, ctype = STATIC[path]
            # eeg-client.js is served from here so every client shares ONE copy — no drift.
            return self._file(os.path.join(APP_ROOT, name), ctype)

        if experimental is not None:
            r = experimental.handle_get(path)
            if r is not None:
                return self._json(*r)
        elif path in ("/claims", "/atlas/reference", "/extract/reference"):
            return self._json(503, _missing("the experimental analysis module", _ATLAS_ERROR))
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        try:
            if path == "/open":
                ports = DAEMON.list_ports()
                name = body.get("port") or (ports[0] if ports else None)
                if not name:
                    return self._json(400, {"error": "no serial device found"})
                return self._json(
                    200,
                    DAEMON.open(
                        name, int(body.get("baud", 115200)), int(body.get("channelCol", 1))
                    ),
                )
            if path == "/close":
                DAEMON.close()
                return self._json(200, DAEMON.status())
            if path == "/session/selftest":
                return self._json(200, durability.disk_selftest(body.get("app", "_selftest")))
            if path in ("/session/init", "/session/update", "/session/finalize"):
                return self._session_op(path, body)
            if path == "/session/orphans":
                return self._json(200, {"orphans": durability.list_orphans(body.get("app"))})
            if path == "/record":
                return self._json(200, DAEMON.start_record(body.get("name")))
            if path == "/record/stop":
                return self._json(200, DAEMON.stop_record())

            # ---- This board's own trust tooling: always answers, no optional tool involved.
            if path in ("/quality", "/bands", "/spectrum"):
                rate, _rate_basis = _rate_for(body)
                samples = _samples_for(body)
                if path == "/quality":
                    # `cfg` passthrough (2026-08-18): `assess()` has always taken a cfg override.
                    # `readout` (top level, or inside `cfg` -- the panel forwards only `cfg`)
                    # selects the checks: EEG keeps the scalp floor and the experimental alpha
                    # ratio; ECG/EMG get rails, mains share and a flat-line floor only.
                    cfg = body.get("cfg")
                    if cfg is not None and not isinstance(cfg, dict):
                        return self._json(400, {"error": "cfg must be an object"})
                    readout = body.get("readout") or (cfg or {}).get("readout") or "eeg"
                    return self._json(
                        200,
                        quality.assess(
                            samples,
                            rate,
                            uv_per_count=float(body.get("uv_per_count", 1.0)),
                            adc_max=float(body.get("adc_max", 1023.0)),
                            mains_hz=(
                                None if body.get("mains_hz") is None else float(body["mains_hz"])
                            ),
                            already_uv=bool(body.get("already_uv", False)),
                            cfg=cfg,
                            readout=readout,
                        ),
                    )
                if path == "/bands":
                    return self._json(200, quality.bands(samples, rate))
                return self._json(
                    200,
                    quality.spectrum(
                        samples,
                        rate,
                        lo_hz=float(body.get("lo_hz", 1.0)),
                        hi_hz=float(body.get("hi_hz", 45.0)),
                        bins=int(body.get("bins", 120)),
                    ),
                )

            # ---- EXPERIMENTAL (experimental.py): the atlas and the extraction layer. The
            # dependency runs THIS way only: they may read the daemon through the two helpers
            # passed in; the daemon never reads them.
            if experimental is not None:
                r = experimental.handle_post(
                    path, body, samples_for=_samples_for, rate_for=_rate_for
                )
                if r is not None:
                    return self._json(*r)
            elif path.startswith("/extract") or path in (
                "/predict",
                "/montage",
                "/simulate",
                "/integration-check",
                "/noise-budget",
                "/detection-curve",
                "/rate-trade",
            ):
                return self._json(503, _missing("the experimental analysis module", _ATLAS_ERROR))
        except KeyError as e:
            return self._err(path, 400, {"error": f"missing required field: {e}"})
        except (ValueError, TypeError) as e:
            # A firewall fired. This is a 400, not a 500: the request was well-formed JSON that
            # described a physically incoherent stimulus, and the message says which axis it broke.
            return self._err(
                path,
                400,
                {
                    "error": str(e),
                    "kind": type(e).__name__,
                    "firewall": isinstance(e, _FIREWALL_ERRORS),
                },
            )
        except Exception as e:
            return self._err(path, 500, {"error": str(e)})
        return self._json(404, {"error": "not found"})

    def _err(self, path, code, obj):
        """An error is still marked experimental when it came from an experimental route."""
        if experimental is not None and experimental.is_route(path):
            obj = experimental.mark(obj)
        return self._json(code, obj)

    def _stream(self):
        """SSE: `data: {"from":N,"total":M,"samples":[...]}` plus a ~1 Hz heartbeat."""
        try:
            cur = int(self._q().get("from", "0"))
        except ValueError:
            cur = 0
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        last_hb = 0.0
        try:
            while True:
                samples, total, actual = DAEMON.read_since(cur)
                if samples:
                    cur = total
                    payload = json.dumps(
                        {
                            "from": actual,
                            "total": total,
                            "samples": samples,
                            "generation": DAEMON.generation,
                        }
                    )
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                now = time.time()
                if now - last_hb >= 1.0:
                    hb = json.dumps({"hb": 1, "total": DAEMON.total, "open": DAEMON.running})
                    self.wfile.write(f"event: hb\ndata: {hb}\n\n".encode())
                    self.wfile.flush()
                    last_hb = now
                time.sleep(0.04)
        except (BrokenPipeError, ConnectionResetError):
            return


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", 8140))
    bind = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    srv = ThreadingHTTPServer((bind, port), Handler)
    pyserial = "yes" if _HAVE_PYSERIAL else "NO — install it"
    print(f"olimex-shield bridge on http://{bind}:{port}  (pyserial={pyserial})")
    print(f"  devices: {DAEMON.list_ports() or 'none detected'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        DAEMON.close()


if __name__ == "__main__":
    main()
