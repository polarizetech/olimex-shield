"""Stories for the signal checks: quality.py and timebase.py. Synthetic input only."""
import math
import random

from autodocsite.story import line, story, table, trace, verdicts, view

FS = 250.0


def synthetic_counts(seconds=20.0, alpha_counts=260.0, noise_counts=25.0, seed=1):
    """10-bit converter counts: a 10 Hz rhythm on a mid-rail baseline, plus Gaussian noise."""
    rng = random.Random(seed)
    return [512 + alpha_counts * math.sin(2 * math.pi * 10.0 * i / FS) + rng.gauss(0, noise_counts)
            for i in range(int(seconds * FS))]


@story(id="preflight-verdict", title="Is this channel worth a session?", page="bridge-api", dataset="synthetic",
       calls=("quality.assess", "quality.spectrum"), badge=None,
       summary="`quality.assess` is the pre-flight check the workbench runs before recording. "
               "Three synthetic channels with known answers: a 10 Hz rhythm, a flat line, and a "
               "signal pinned against the converter's rail.")
def preflight_verdict():
    import quality

    channels = {
        "10 Hz rhythm": synthetic_counts(),
        "flat line": [512.0] * int(20 * FS),
        "railed": [1023.0 if i % 50 < 45 else 512.0 for i in range(int(20 * FS))],
    }
    verdict = {name: quality.assess(samples, FS) for name, samples in channels.items()}

    spec = quality.spectrum(channels["10 Hz rhythm"], FS)
    peak_hz = spec["freqs"][max(range(len(spec["amps"])), key=spec["amps"].__getitem__)]
    spacing_hz = spec["freqs"][1] - spec["freqs"][0]
    return view(
        input=[trace("The three synthetic channels (first 2 s)", None, FS, seconds=2, unit="counts", series=channels)],
        output=[
            verdicts("quality.assess(samples, rate_hz)['level']", [
                {"key": name, "verdict": v["level"], "meta": f"ready: {v['ready']}",
                 "reason": "; ".join(v["reasons"]) or f"amplitude {v['amplitude_uv']:.0f} µV, alpha SNR {v['alpha_snr']:.0f}",
                 "tone": "yes" if v["level"] == "good" else "none" if v["level"] == "marginal" else "no"}
                for name, v in verdict.items()],
                caption="A plausibility heuristic, as its own `method` field says: it checks that a channel "
                        "could be a signal, not that it is one."),
            verdicts("quality.spectrum: is the 10 Hz line the tallest point?", [
                {"key": "peak of the drawn spectrum", "verdict": "present" if abs(peak_hz - 10.0) < 0.5 else "absent",
                 "meta": f"tallest point at {peak_hz:.2f} Hz",
                 "reason": f"the input is a 10 Hz sine of 260 counts in 25 counts of noise; the spectrum is drawn from "
                           f"{len(spec['freqs'])} points {spacing_hz:.2f} Hz apart, taken from a {spec['resolution_hz']:.2f} Hz transform"}]),
            line("quality.spectrum of the 10 Hz channel", spec["freqs"], spec["amps"],
                 xlabel="frequency (Hz)", ylabel="amplitude (counts)", xunit="Hz", markers=[{"x": 10.0, "label": "10 Hz (the input)"}]),
        ],
        facts=[(name, v["level"]) for name, v in verdict.items()] + [("spectrum peak", f"{peak_hz:.2f} Hz")],
        raw={name: {k: v[k] for k in v if k != "thresholds"} for name, v in verdict.items()},
    )


@story(id="measured-sample-rate", title="What rate does the board actually deliver?", page="bridge-api", dataset="synthetic",
       calls=("timebase.RateEstimator",), badge=None,
       summary="The sketch declares 250 Hz; a real board runs slightly slow. `RateEstimator` measures the "
               "delivered rate against the host clock. Here a simulated board delivers 248.3 Hz, and "
               "the estimator has to find that without being told.")
def measured_sample_rate():
    import timebase

    true_hz, batch = 248.3, 25
    est = timebase.RateEstimator(declared_hz=250.0)
    count, history = 0, []
    while count < 180 * true_hz:                      # three minutes, 25 samples at a time
        count += batch
        est.add(host_t=count / true_hz, count=count)  # `count` is cumulative
        history.append((count / true_hz, est.estimate()["measured_hz"]))

    final = est.estimate()
    measured = [(t, hz) for t, hz in history if hz is not None]
    return view(
        output=[
            line("estimate()['measured_hz'] as samples arrive", [t for t, _ in measured], [hz for _, hz in measured],
                 xlabel="host time (s)", ylabel="measured rate (Hz)", xunit="s", yunit="Hz",
                 caption=f"No estimate is given before {measured[0][0]:.0f} s: it needs 30 s across at least 6 five-second bins."),
            table("estimate() after 180 s", ["field", "value"], [[k, v] for k, v in final.items() if not isinstance(v, (dict, list))]),
        ],
        facts=[("declared", "250 Hz"), ("simulated", f"{true_hz} Hz"), ("estimated", f"{final['measured_hz']:.3f} Hz"),
               ("error", f"{final['error_ppm']:.0f} ppm")],
        raw=final,
    )
