"""R-peak detection with Elgendi's two event-related moving averages.
EXPLORATORY (scope/ecg-beats.md).

Elgendi 2013, Fast QRS Detection with an Optimized Knowledge-Based Method: Evaluation on 11
Standard ECG Databases, PLoS ONE, doi:10.1371/journal.pone.0073557: band-pass 8-20 Hz
(third-order Butterworth, both directions), square, a 97 ms moving average (QRS) against a
611 ms one (beat) plus beta times the mean of the squared signal, blocks at least 97 ms wide
are QRS complexes, and the R peak is the largest absolute value in each. Stdlib only.
"""

from __future__ import annotations

import math

LOW_HZ = 8.0  # Elgendi 2013: passband 8-20 Hz
HIGH_HZ = 20.0
ORDER = 3  # Elgendi 2013: third-order Butterworth, applied forward and backward
W1_S = 0.097  # Elgendi 2013: the QRS window, 97 ms
W2_S = 0.611  # Elgendi 2013: the beat window, 611 ms
BETA = 0.08  # Elgendi 2013: offset fraction (optimal 2-10 %; the extracted text prints 0.8)


def odd_window(seconds: float, rate: float) -> int:
    """A window in samples, rounded to the nearest odd integer (Elgendi 2013)."""
    return 2 * int(math.floor(seconds * rate / 2.0)) + 1


def _sections(kind: str, fc: float, rate: float) -> list[tuple]:
    """A third-order Butterworth low- or high-pass as one first-order and one second-order (Q = 1)
    section, by the bilinear transform with prewarping: ((b0, b1, b2), (a1, a2)) each."""
    k = math.tan(math.pi * fc / rate)
    a1_1 = (k - 1.0) / (k + 1.0)
    if kind == "low":
        first = ((k / (k + 1.0), k / (k + 1.0), 0.0), (a1_1, 0.0))
    else:
        first = ((1.0 / (k + 1.0), -1.0 / (k + 1.0), 0.0), (a1_1, 0.0))
    norm = 1.0 / (1.0 + k + k * k)
    a = (2.0 * (k * k - 1.0) * norm, (1.0 - k + k * k) * norm)
    if kind == "low":
        b0 = k * k * norm
        second = ((b0, 2.0 * b0, b0), a)
    else:
        second = ((norm, -2.0 * norm, norm), a)
    return [first, second]


def _run(x: list[float], sections: list[tuple]) -> list[float]:
    y = list(x)
    for (b0, b1, b2), (a1, a2) in sections:
        out = [0.0] * len(y)
        x1 = x2 = y1 = y2 = 0.0
        for i, v in enumerate(y):
            o = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
            x2, x1, y2, y1 = x1, v, y1, o
            out[i] = o
        y = out
    return y


def bandpass(x: list[float], rate: float) -> list[float]:
    """8-20 Hz, third-order Butterworth high- then low-pass, run forward and then backward
    (zero phase)."""
    mean = sum(x) / len(x)
    sec = _sections("high", LOW_HZ, rate) + _sections("low", HIGH_HZ, rate)
    y = _run([v - mean for v in x], sec)
    return _run(y[::-1], sec)[::-1]


def moving_average(z: list[float], w: int) -> list[float]:
    """Centred moving average over w samples (w odd); at the ends, over the samples there are."""
    n, h = len(z), w // 2
    pre = [0.0]
    for v in z:
        pre.append(pre[-1] + v)
    out = []
    for i in range(n):
        lo, hi = max(0, i - h), min(n, i + h + 1)
        out.append((pre[hi] - pre[lo]) / (hi - lo))
    return out


def r_peaks(x: list[float], rate: float) -> list[int]:
    """Indices of the R peaks in x. A block still open at the last sample is not reported yet:
    it is reported by a later request, once it has closed."""
    n = len(x)
    w1, w2 = odd_window(W1_S, rate), odd_window(W2_S, rate)
    if n < 2 * w2:
        return []
    y = bandpass(x, rate)
    z = [v * v for v in y]
    ma_qrs, ma_beat = moving_average(z, w1), moving_average(z, w2)
    alpha = BETA * (sum(z) / n)
    peaks, start = [], None
    for i in range(n):
        inside = ma_qrs[i] > ma_beat[i] + alpha
        if inside and start is None:
            start = i
        elif not inside and start is not None:
            if i - start >= w1:
                peaks.append(max(range(start, i), key=lambda j: abs(y[j])))
            start = None
    return peaks
