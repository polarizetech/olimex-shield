# Hardware notes

What was measured on one board, and what is still open. The detailed log is
[`apps/server/RIG.md`](../apps/server/RIG.md). Wiring and flashing are in
[`apps/olimex-shield/README.md`](../apps/olimex-shield/README.md).

| | |
|---|---|
| Analog band | **0.16–40 Hz, in hardware before the ADC.** Nothing outside it can be recovered by software. |
| Sample rate | Declared 250 Hz. **Measured ~249.83 Hz (≈ −680 ppm), and it drifts.** The bridge measures the real rate against the computer's clock and records both numbers. |
| Resolution | 10-bit ADC. The code uses **7.9 µV per count**, derived from the shield's built-in calibration square wave at its nominal ~250 µV peak to peak (about 31.6 counts). That amplitude is the manufacturer's nominal value and has not been checked with an externally injected signal. The datasheet gain implies about 1.72. Until it is checked, treat every µV and nV figure as provisional. |
| Channels | One differential channel per shield. The sketch also prints `A1`; that has not been shown to be a second input. |
| Mains | Floating leads pick up 60/50 Hz strongly. Running the laptop on battery removes most of it. |

## What this means

- **Resting alpha** at the back of the head is the easiest check, and it has been seen on this rig.
- **A 40 Hz auditory steady-state response** is inside the band, but it has **not yet been shown**
  on this rig. Nothing here has recorded a response to a known stimulus.
- **Brainstem responses** (ABR, FFR) have most of their energy far above 40 Hz, which the analog
  filter removes.
- **Skin conductance (EDA)** is not possible: it needs a current source, and the 0.16 Hz high-pass
  removes the slow signal.
- **EMG** is heavily limited by the 40 Hz low-pass: most surface-EMG power lies above it. You can see
  a muscle switch on and off, but not its spectrum.

## Open questions

- **Calibration.** Inject a known external signal at the input and measure µV per count.
- **Input-referred noise.** Measure it with shorted inputs. The published 40 Hz figures are in-band
  power of scalp recordings, not instrument noise.
- **Timing.** No latency or jitter figure exists between a stimulus and the recording.
- **Impedance.** The signal-plausibility check does not measure electrode impedance.
- **Lost samples.** The bridge now counts malformed lines and timestamp gaps and records them with
  each session; the rate measurement assumes none were lost.
