"""Development checks for olimex-shield-ext-beats (scope/ecg-beats.md F1): Elgendi 2013 parameters,
windows, detection, route."""

import math
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server"))
sys.path.insert(0, str(ROOT / "extensions" / "beats"))

import olimex_shield_ext_beats as beats  # noqa: E402
from olimex_shield_ext_beats import detect  # noqa: E402


def synthetic(rate=250, seconds=10.0):
    """Gaussian R-like peaks on a 512-count baseline, at 1.0 + m*0.857 s."""
    tps = [1.0 + m * 0.857 for m in range(10)]
    n = int(seconds * rate)
    x = []
    for i in range(n):
        t = i / rate
        x.append(512 + sum(200 * math.exp(-((t - tp) ** 2) / (2 * 0.01**2)) for tp in tps))
    return x, tps


class DevCheck(unittest.TestCase):
    def test_parameters_are_elgendis(self):
        self.assertEqual(detect.LOW_HZ, 8.0)
        self.assertEqual(detect.HIGH_HZ, 20.0)
        self.assertEqual(detect.ORDER, 3)
        self.assertEqual(detect.W1_S, 0.097)
        self.assertEqual(detect.W2_S, 0.611)
        self.assertEqual(detect.BETA, 0.08)

    def test_odd_windows_at_250_hz(self):
        self.assertEqual(detect.odd_window(0.097, 250), 25)
        self.assertEqual(detect.odd_window(0.611, 250), 153)

    def test_finds_synthetic_r_peaks(self):
        x, tps = synthetic()
        peaks = detect.r_peaks(x, 250)
        expected = [round(tp * 250) for tp in tps]
        for tp in tps:
            if 1.0 <= tp <= 9.0:
                target = round(tp * 250)
                self.assertTrue(any(abs(p - target) <= 2 for p in peaks), f"no peak near {target}")
        for p in peaks:
            self.assertTrue(
                any(abs(p - e) <= 2 for e in expected), f"peak {p} is not near any true peak"
            )

    def test_route_numbers_each_beat_once(self):
        x, _ = synthetic()
        stamps = [i * 4000 for i in range(len(x))]
        ctx = types.SimpleNamespace(
            rate_for=lambda b: (250.0, "declared"),
            timed_samples_for=lambda b: {"samples": x, "t_us": stamps, "arrived": 100.0},
            default_rate=250.0,
        )
        beats._STATE = {"k": 0, "beats": []}
        first = beats._beats({}, ctx)
        second = beats._beats({}, ctx)
        self.assertEqual(first[0], 200)
        self.assertEqual(second[0], 200)
        self.assertEqual([b["k"] for b in second[1]["beats"]], [b["k"] for b in first[1]["beats"]])
        for b in first[1]["beats"]:
            self.assertEqual(b["t_us"] % 4000, 0)
            self.assertIn(b["t_us"], stamps)
        for b in first[1]["beats"][1:]:
            self.assertIsNotNone(b["rr_s"])
            self.assertLess(abs(b["rr_s"] - 0.857), 0.01)
        self.assertEqual(second[1]["newest_t_us"], stamps[-1])

    def test_rr_across_the_wrap(self):
        x, _ = synthetic()
        stamps = [(2**32 - 2_000_000 + i * 4000) % 2**32 for i in range(len(x))]
        ctx = types.SimpleNamespace(
            rate_for=lambda b: (250.0, "declared"),
            timed_samples_for=lambda b: {"samples": x, "t_us": stamps, "arrived": 100.0},
            default_rate=250.0,
        )
        beats._STATE = {"k": 0, "beats": []}
        status, body = beats._beats({}, ctx)
        self.assertEqual(status, 200)
        for b in body["beats"]:
            if b["rr_s"] is not None:
                self.assertLess(abs(b["rr_s"] - 0.857), 0.01)
            self.assertGreaterEqual(b["behind_newest_s"], 0)
            self.assertLessEqual(b["behind_newest_s"], len(x) / 250.0)

    def test_no_board_clock_is_409(self):
        x, _ = synthetic()
        ctx = types.SimpleNamespace(
            rate_for=lambda b: (250.0, "declared"),
            timed_samples_for=lambda b: {"samples": x, "t_us": [None] * len(x), "arrived": 100.0},
            default_rate=250.0,
        )
        status, _ = beats._beats({}, ctx)
        self.assertEqual(status, 409)

    def test_not_enough_samples_is_409(self):
        def raise_short(b):
            raise ValueError("only 0 samples")

        ctx = types.SimpleNamespace(
            rate_for=lambda b: (250.0, "declared"),
            timed_samples_for=raise_short,
            default_rate=250.0,
        )
        status, _ = beats._beats({}, ctx)
        self.assertEqual(status, 409)


if __name__ == "__main__":
    unittest.main()
