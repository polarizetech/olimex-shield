"""timebase.py — the sample rate the board ACTUALLY delivers, measured against the host clock.

Stdlib only; imported by the acquisition daemon, so it must not be able to fail on a missing
dependency. Pure: no I/O, no threads, no clock of its own — the caller passes timestamps in.

WHY THIS EXISTS (RIG.md, 2026-09-15)
    The board reports 250 Hz because it schedules samples off its own `micros()`, and that clock is
    the thing in question. Against the host clock this board runs at 249.839 Hz, -644 ppm. Nothing
    that only draws or checks contact notices; a lock-in at a nominal frequency does — a 60 Hz line
    40 dB above the floor read "not detected" at 40 s. So the daemon measures the rate it is
    actually receiving, and says how well it knows it.

METHOD
    Each time a chunk arrives, record (host time, samples received so far). If the board delivered
    exactly `declared` Hz, `host_t - count/declared` (the latency) would be flat. Its slope is the
    clock error. Latency can only ever ADD delay — USB polling, OS buffering, a busy reader — so
    the clean line is the LOWER ENVELOPE: take the minimum latency in each 5 s bin and fit a line
    through those minima. On this rig that gave 0.16 ms of scatter over 123 s where a plain
    least-squares fit would have absorbed any growth in buffering into the answer.

WHAT IT ASSUMES, stated so nobody has to rediscover it
    - No samples are lost on the wire. A lost sample makes the count lag host time permanently and
      reads as a slower clock. RIG.md measured zero drops in 46,212 rows at 115200 baud.
    - The host clock is good to a few ppm (NTP-disciplined). Nothing here can check that.
    - The rate is steady over the fit window. The window slides (`keep_s`), so slow drift — a
      resonator warming up — is followed rather than averaged away.
"""

from __future__ import annotations

import math

BIN_S = 5.0  # one latency minimum per bin
MIN_BINS = 6  # a slope from fewer points is not reported
MIN_SPAN_S = 30.0  # nor from a shorter stretch
KEEP_S = 600.0  # sliding window: follow slow drift rather than average it away
# A stretch this long with NO samples means the count stopped tracking time -- the board rebooted
# or the stream stalled -- and every point before it is on a different line. Start over.
# Found on the real rig: opening the port delivers stale lines still sitting in the OS buffer from
# the previous session INSTANTLY, then the Arduino resets and says nothing for 1.62 s. That early
# instant became the lowest latency of its bin and dragged a -685 ppm clock to -3300 ± 1491.
GAP_RESET_S = 1.0


class RateEstimator:
    def __init__(
        self,
        declared_hz: float,
        bin_s: float = BIN_S,
        min_bins: int = MIN_BINS,
        min_span_s: float = MIN_SPAN_S,
        keep_s: float = KEEP_S,
        gap_reset_s: float = GAP_RESET_S,
    ):
        if declared_hz <= 0:
            raise ValueError("declared rate must be positive")
        self.declared = float(declared_hz)
        self.bin_s, self.min_bins = float(bin_s), int(min_bins)
        self.min_span_s, self.keep_s = float(min_span_s), float(keep_s)
        self.gap_reset_s = float(gap_reset_s)
        self.reset()

    def reset(self):
        self._bins: dict[
            int, tuple[float, float]
        ] = {}  # bin -> (board_s, latency_s) at the minimum
        self._t0 = None
        self._last_count = 0
        self._start_count = 0
        self._last_host = None
        self._latest_bin = None
        self.restarts = getattr(self, "restarts", -1) + 1

    def add(self, host_t: float, count: int):
        """`count` samples had arrived by host time `host_t` (seconds, monotonic)."""
        if count <= 0:
            return
        if count < self._last_count:  # the counter restarted: a new port, a new clock
            self.reset()
        elif self._last_host is not None and host_t - self._last_host >= self.gap_reset_s:
            restarts = self.restarts
            self.reset()  # a reboot or a stall: the old line no longer applies
            self.restarts = restarts + 1
        if self._t0 is None:
            self._start_count = count
        self._last_host = host_t
        self._last_count = count
        # Counted from the restart, so samples before a gap (stale buffered lines) never shift x.
        board_s = (count - self._start_count) / self.declared
        if self._t0 is None:
            self._t0 = host_t - board_s
        lat = (host_t - self._t0) - board_s
        b = int(board_s // self.bin_s)
        self._latest_bin = b
        cur = self._bins.get(b)
        if cur is None or lat < cur[1]:
            self._bins[b] = (board_s, lat)
        oldest = b - int(math.ceil(self.keep_s / self.bin_s))
        for k in [k for k in self._bins if k < oldest]:
            del self._bins[k]

    def estimate(self) -> dict:
        # The newest bin is still filling, and its minimum is not yet a minimum.
        done = sorted((k, v) for k, v in self._bins.items() if k != self._latest_bin)
        span = (done[-1][1][0] - done[0][1][0]) if len(done) >= 2 else 0.0
        out = {
            "declared_hz": self.declared,
            "measured_hz": None,
            "error_ppm": None,
            "uncertainty_ppm": None,
            "span_s": round(span, 1),
            "bins": len(done),
        }
        if len(done) < self.min_bins or span < self.min_span_s:
            have = (self._last_count - self._start_count) / self.declared
            out["basis"] = (
                f"not yet measured: needs {self.min_span_s:g} s of acquisition in at "
                f"least {self.min_bins} {self.bin_s:g}-s bins; have {have:.0f} s"
            )
            return out
        xs = [v[0] for _, v in done]
        ys = [v[1] for _, v in done]
        n = len(xs)
        mx, my = sum(xs) / n, sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys)]
        sigma = math.sqrt(sum(r * r for r in resid) / max(1, n - 2))
        stderr = sigma / math.sqrt(sxx)
        # slope = host seconds per board second, minus one. True rate = declared / (1 + slope).
        measured = self.declared / (1.0 + slope)
        out.update(
            {
                "measured_hz": round(measured, 5),
                "error_ppm": round((measured / self.declared - 1.0) * 1e6, 1),
                # Statistical only: the fit's own scatter. It says nothing about the host clock.
                "uncertainty_ppm": round(stderr * 1e6, 1),
                "scatter_ms": round(sigma * 1e3, 3),
                "basis": (
                    f"host clock, lower envelope of latency: {n} {self.bin_s:g}-s minima over "
                    f"{span:.0f} s. Assumes no samples lost on the wire and a host clock good to "
                    f"a few ppm."
                ),
            }
        )
        return out


# ------------------------------------------------------------------------ stream integrity --
#: `micros()` on the AVR is a 32-bit unsigned long: it wraps to 0 every 2**32 us (~71.6 min).
T_US_MODULUS = 2**32
#: A step more than this fraction of the declared period away from it is not jitter. The board's
#: steps are 3988-4012 us (RIG.md: the AVR's 4 us `micros()` resolution), so 0.5 x 4000 = 2000 us of
#: tolerance is far outside jitter and far inside one missing sample (a step of 8000).
GAP_TOLERANCE = 0.5


class StreamIntegrity:
    """Counts what the wire lost, from the board's own `t_us` column. Pure; no clock of its own.

    What it counts, and what it never does:
      - `parse_errors`: lines that were not comments and did not yield both `t_us` and the
        selected channel. They are DROPPED, never replaced -- no fake sample is ever inserted.
      - `gaps`: steps longer than the declared period by more than the tolerance, i.e. at least
        one sample the board scheduled never arrived. `missing_estimate` sums round(step/period)-1
        over them; it is an estimate from the board's clock, and it is the only one available.
      - `short_steps`: steps shorter than the period by more than the tolerance (a duplicated or
        corrupted line).
      - `wraps`: `t_us` rolled over 2**32 us; handled by modular arithmetic, not an error.
      - `clock_resets`: `t_us` jumped backwards by more than half the modulus -- the board
        rebooted mid-stream. Counted separately, not as a gap.

    `timebase.RateEstimator` assumes no samples are lost; a non-zero `gaps` is the evidence that
    the assumption failed.
    """

    def __init__(self, declared_hz=250.0, tolerance=GAP_TOLERANCE):
        self.period_us = 1e6 / float(declared_hz)
        self.tolerance = float(tolerance)
        self.reset()

    def reset(self):
        self.prev = None
        self.lines = 0
        self.parse_errors = 0
        self.gaps = 0
        self.missing_estimate = 0
        self.max_gap_us = 0
        self.short_steps = 0
        self.wraps = 0
        self.clock_resets = 0

    def parse_error(self):
        self.parse_errors += 1

    def add(self, t_us):
        """One parsed `t_us`. Returns (kind, step_us); kind is None for the first sample, else
        'ok', 'gap', 'short' or 'reset'."""
        t = int(t_us) % T_US_MODULUS
        self.lines += 1
        prev, self.prev = self.prev, t
        if prev is None:
            return None, None
        step = (t - prev) % T_US_MODULUS
        if step >= T_US_MODULUS // 2:
            self.clock_resets += 1
            return "reset", t - prev
        if t < prev:
            self.wraps += 1
        tol = self.tolerance * self.period_us
        if step > self.period_us + tol:
            self.gaps += 1
            self.missing_estimate += max(1, int(round(step / self.period_us)) - 1)
            self.max_gap_us = max(self.max_gap_us, step)
            return "gap", step
        if step < self.period_us - tol:
            self.short_steps += 1
            return "short", step
        return "ok", step

    def snapshot(self):
        return {
            "samples_timed": self.lines,
            "parse_errors": self.parse_errors,
            "gaps": self.gaps,
            "missing_estimate": self.missing_estimate,
            "max_gap_us": self.max_gap_us,
            "short_steps": self.short_steps,
            "wraps": self.wraps,
            "clock_resets": self.clock_resets,
            "declared_period_us": self.period_us,
            "tolerance_us": self.tolerance * self.period_us,
            "basis": "the board's own t_us column (micros(), 32-bit, wraps every ~71.6 min); "
            "a gap is a step > declared period + tolerance. Malformed lines are dropped and "
            "counted, never replaced.",
        }
