# RIG.md — what the hardware on this desk actually is

Measured 2026-08-18, live, with the board attached. Everything here was **probed, not assumed** —
the first attempt guessed the OpenEEG convention (57600) and got zero samples for eleven seconds.

| | |
|---|---|
| Port | `/dev/cu.usbmodem1301` (2026-08-18); `/dev/cu.usbmodem21301` (2026-09-15) — the suffix follows the USB socket, so never hardcode it |
| **Baud** | **115200** — *not* 57600. The bridge's default is already 115200; a wrong guess is what cost the first probe. |
| Firmware banner | `# ArduinoEKG ready` |
| Wire format | `t_us,ch0,ch1` CSV, `#` comment lines, **two channels** |
| Sample period | 4000 µs → 250.0 Hz **by the board's own clock** — which is circular. **Against the host clock: 249.839 Hz, −644 ppm** (2026-09-15, below). |
| ADC | 10-bit, resting near mid-scale (511.5) |
| **Scale** | **7.9 µV/count — NOT externally verified.** Derived in an earlier internal app from the shield's **built-in calibration square wave** at its *nominal* ~250 µV peak-to-peak (≈ 31.6 counts; 250 / 31.6 = 7.9). The cal amplitude is the manufacturer's nominal figure; neither it nor this scale has been checked with an externally injected signal of known amplitude. The datasheet gain implies **1.72**. An earlier note called 7.9 "independently recovered from the samples"; that check multiplied by 7.9 and read 7.9 back, so it was circular and is withdrawn. `rig.UV_PER_COUNT_PROVENANCE`; exported as the BIDS sidecar's `ScalingProvenance`. |

## 2026-09-15 — validated with leads attached to the shield and nobody on them

Everything below came off `/dev/cu.usbmodem21301`: two raw captures read straight from the port
before the bridge held it (61 s and 125 s), then the bridge and four `signal-panel` client pages
on the same open port. No subject, no recording kept.

### The sample rate is 249.839 Hz, not 250 — and it matters for lock-in, not for anything else

- **Board clock:** `t_us` steps are 3988–4012 µs (the AVR's 4 µs `micros()` resolution),
  averaging exactly 4000. **Zero dropped samples** in 46,212 rows across both captures. This is
  what the old "measured off `t_us`" line was measuring — the board agreeing with itself.
- **Host clock:** read in bulk (the OS buffer never exceeded 305 bytes, so the reader never fell
  behind), timestamped per chunk, and fitted to the **lower envelope** of latency — latency can
  only add delay, so its minimum is the clean line. Rate error **−644 ppm** (slow), scatter of the per-5-s
  minima **0.16 ms over 123 s**. The earlier 61 s capture, read line by line, gave −599 ppm in the
  same direction; the bulk-read figure is the one to trust. It rests on the Mac's clock being good
  to a few ppm (NTP-disciplined) and on nothing else.
- **Mains is not a usable referee at this precision.** At an assumed 250 Hz, the 60 Hz line read
  60.0055 Hz in the first capture and 60.0489 Hz in the second, a few minutes apart. That 43 mHz
  swing is the grid, and it is larger than the error being measured.
- **What −644 ppm does, measured on the second capture through the bridge's own `/extract`:**

  | window | lock-in at 60.000 Hz | lock-in at 60.049 Hz (mains as the board sees it) |
  |---|---|---|
  | 5 s | p 2.6e-17, 24.4 dB | p 2.6e-17, 24.4 dB |
  | 20 s | p 3.4e-4, 10.5 dB, amplitude down to 17% | p 3.0e-23, 29.5 dB |
  | 40 s | **p 0.76, −5.5 dB — "not detected"** | p 3.0e-15, 22.6 dB |

  **A line 40 dB above the floor, carrying 94% of the power, reads as absent at 40 s.** This is
  the motivating case for measuring the rate at all, now shown on this rig: a 40 Hz drive played from the computer
  lands at ~40.026 Hz in these samples, and a minutes-long lock-in at the nominal frequency
  averages it toward zero. **The extraction layer did not lie about it** — it tiered the result
  `MEASURED_UNSYNCED` and said "bounds the response, does not prove absence" — but a reader who
  trusts the p-value would conclude the opposite of the truth. Any lock-in here needs a
  co-recorded reference or the measured rate. Ordinary displays, contact checks and heart rate are
  unaffected (a 0.06% timebase error is invisible to them).
- **`bridge /status` reported `rate: 250`, a constant, and consumers labelled it "measured"** —
  one client's log said "Analysis uses the measured 250 Hz". Fixed the same day: see
  the next section.

### The bridge now measures the rate itself (`timebase.py`)

- **The method above runs inside the daemon**, continuously: the reader timestamps each chunk
  right after `read()` returns, `RateEstimator` bins latency minima every 5 s over a sliding
  600 s window, and `/status` carries `rateMeasured`, `rateErrorPpm`, `rateUncertaintyPpm` and
  `rateBasis`. **`null` until 30 s over 6 bins** — never a guess. `rate` stays 250 and is now
  documented as declared.
- **The board drifts, so no constant could have held it.** −644 ppm in the morning, **−685 ppm**
  that afternoon, −682.1 ± 0.4 ppm over 414 s at the end of the day. The afternoon figure was
  checked two ways on one capture: the offline method gave −685.1, the estimator −685.0 — the
  41 ppm is the board, not the estimator.
- **Stale lines found a real bias.** A capture taken right after another process released the
  port started with lines still in the OS buffer, delivered instantly, then 1.62 s of silence
  while the Arduino reset. That early instant became a bin minimum and dragged −685 ppm to
  **−3300 ± 1491**. Any 1 s gap now restarts the fit (`GAP_RESET_S`); the same data then reads
  −690.8 ± 2.3.
- **Who uses it:** `/extract`, `/quality`, `/bands` and `/spectrum` with `source:"live"` use the
  measured rate once it exists and say which in `rate_basis`; a caller-supplied `rate` always
  wins. `signal-panel` exposes it as `analysisRate`, and its lock-in widget prints *measured* or
  *DECLARED — not yet measured*. Client captures record `rate_hz` and `rate_basis`.
- **What it recovers, live:** 60 Hz at 40 s — **p 0.86 at the declared 250 Hz, p 2.2e-4 at the
  measured rate**. Through the panel on another client page, the lock-in widget found mains at
  p 1.6e-14 over 20 s against 249.830 Hz measured.
- **Assumes** no samples lost on the wire (zero seen in 46,212 rows) and a host clock good to a
  few ppm. It cannot check either.

### Mains, noise and the two channels

- With leads on the shield and nothing on them: **ch0 16.9 µV RMS (sd 2.1 counts), 94% of its
  power in 58–62 Hz**, the 60.02 Hz line 40 dB above the median bin. Compare 2026-08-18 with
  *nothing* attached: 5.0 µV, span 3 counts. Floating leads are an antenna, as expected; the
  front end's nominal 40 Hz low-pass does not stop it. `quality.assess` returns **unusable**
  (amplitude far below the 100 µV scalp-EEG plausibility floor, mains 30–66× the 2–40 Hz power) —
  the correct answer.
- 13 distinct ADC values in 61 s: the 7.9 µV step (itself the unverified, cal-derived scale) is
  half the noise — the dither boundary.
- **The analog low-pass cannot be seen in this data.** Median power 45–55 Hz sits only 3.9 dB
  under 5–35 Hz because both are at the white quantisation floor; a leads-off capture measures the
  ADC, not the filter.
- **ch0 and ch1 correlate at +0.89** — +0.93 in the mains band, and still **+0.64 with 55–65 Hz
  removed** — and ch1 lags ch0 by **23° at 60 Hz (~1.1 ms)**, far more than the ~0.1 ms between
  the two back-to-back `analogRead` calls. ch1 is carrying the same environment through a different
  (higher-impedance) path. That is consistent with a floating pin and does not establish a second
  differential input; **the touch test above is still the only thing that will.**

### The bridge and the panel on real hardware

- `/ports` lists the device; `/open` returns in 30 ms, but **the first sample arrives 1.62 s
  later** — opening the port resets the Arduino, which then boots. A second `/open` while streaming
  kept `total` and `generation` (no reset), as designed.
- **The panel's "already-open port" fix holds on the real device:** with the bridge holding
  10,022 and then 27,092 samples, two client pages (an ECG monitor and a plant-signal reader) each received a
  first batch of exactly **500 samples (2 s)**, not the ring.
- Every consumer badged the source **MEASURED** (`status.demo` false) and reported contact
  **unusable**; the ECG page's 16.8 µV / 29.57× matched the raw capture's 16.9 µV / 29.53×;
  the plant reader's config removed the alpha-ratio reason that the scalp defaults raise (the check
  is now readout-aware and does this itself for non-EEG readouts);
  both hookup guides gated the real port; a third client found the device without the
  no-device prompt and took a 3 s probe of 753 samples. The port was released at the end.

### From the firmware, not measured

`t_us` is `micros()` in a 32-bit `unsigned long`, so **it wraps to 0 every 71.6 minutes**. The
sketch's scheduling survives the wrap; anything that reads timing out of the `t_us` column across
a longer session must handle it. Since 2026-09-25 the bridge reads `t_us` too
(`timebase.StreamIntegrity`): it counts gaps (steps > 1.5 × the declared period) with modular
arithmetic, so the wrap is a normal step, and a backwards jump is counted as a clock reset. It
writes `t_us` into the black box and never inserts a sample.

## What a no-electrode capture looks like here

With nothing attached (2500 samples, 10 s):

- span **3 counts**, amplitude **5.0 µV** — the channel is at its own floor, as it should be
- **60 Hz mains at +32.2 dB, p = 1.9e-26** — a decisive detection, and the single best proof the
  whole chain works: a real external signal is being picked up and correctly measured
- 50 Hz **not** significant (p = 0.071), which is right for a 60 Hz country
- in-band noise at 5.4 Hz: **322 nV over 10 s**, inside the 64–750 nV range this tool's own
  validation found across six prior captures — though that range is at 40 Hz over 60 s, so the
  comparison is loose (range and count corrected 2026-09-13 from 65–750 across eight)

`quality.assess` returns **unusable**, and that is the correct answer: nothing is attached to a
body. The verdict is about signal plausibility, not about the instrument, and it does not measure
impedance.

## Two channels, and what that does NOT yet establish

The sketch streams `ch0` and `ch1`, and both move independently (sd 0.65 and 0.51 counts, means
509.4 and 502.8). **This does not establish that the shield drives two independent differential
inputs.** A single SHIELD-EKG-EMG is one channel; `ch1` may simply be a floating Arduino pin, and a
floating pin also wanders by a fraction of a count.

It matters because any bilateral *electrical* recording design depends on it: if `ch1` is not a
second input, a second shield is needed. **The cheapest test: short
or touch one channel's inputs and see which column responds.** Until that is run, treat `ch1` as
unidentified rather than as a second channel.

## Consuming the stream: two traps, both hit here

**There is no `/recent` HTTP route.** `recent()` is a method on `eeg-client.js`, which keeps its own
ring fed by `/stream`. A consumer that fetches `/bridge/recent` gets a 404 body where it expected
samples, and — because the body is JSON — nothing throws.

**A JSON proxy cannot carry `/stream`.** `urlopen().read()` never returns on an SSE response. Any
project proxying the bridge same-origin needs a line-by-line pipe; the workbench's `/bridge/stream`
(`apps/web/serve.py`) is one.

**And "open" is not "streaming."** Reopening the port resets `total` to 0 and bumps `generation`, so
a readiness check must watch for the counter to *increase* between polls rather than compare against
a count taken before connecting.
