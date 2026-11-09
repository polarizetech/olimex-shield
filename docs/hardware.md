# Hardware notes

What the board is, from the manufacturer's specification, and what you should measure on your own
board before trusting it. Wiring, flashing and the quick checks are in
[`apps/olimex-shield/README.md`](../apps/olimex-shield/README.md#checking-your-board).

One board's measured characterisation (sample-rate error, scale, noise) is published in the
Polarize.Tech post
[*Can a $70 board tell me I'm wrong?*](https://polarize.tech/blog/can-a-70-dollar-board-tell-me-im-wrong/).
Those are results for that board, not constants of this tool.

| | |
|---|---|
| Analog band | **0.16–40 Hz, in hardware before the ADC.** Nothing outside it can be recovered by software. |
| Sample rate | Declared 250 Hz (the sketch's schedule). Boards run slightly off nominal and drift; the bridge measures the real rate against the computer's clock and records both numbers. |
| Resolution | 10-bit ADC. The code's **default is 7.9 µV per count**, from one board's built-in calibration signal at its nominal amplitude. The gain trimmer differs per board: calibrate yours and set `OLIMEX_UV_PER_COUNT`. The datasheet gain implies about 1.72. Until you calibrate, treat every µV and nV figure as provisional. |
| Channels | One differential channel per shield. The sketch also prints `A1`; that has not been shown to be a second input. |
| Mains | Floating leads pick up 60/50 Hz strongly. Running the laptop on battery removes most of it. |

## What this means

- **Resting alpha** at the back of the head is inside the band and is the easiest first check.
- **A 40 Hz auditory steady-state response** is inside the band, but this tool does not show that
  it can be recovered on this board; that is a question for your own preregistered experiment.
- **Brainstem responses** (ABR, FFR) have most of their energy far above 40 Hz, which the analog
  filter removes.
- **Skin conductance (EDA)** is not possible: it needs a current source, and the 0.16 Hz high-pass
  removes the slow signal.
- **EMG** is heavily limited by the 40 Hz low-pass: most surface-EMG power lies above it. You can see
  a muscle switch on and off, but not its spectrum.

## What to measure on your board

- **Calibration.** Inject a known external signal at the input and measure µV per count. Set
  `OLIMEX_UV_PER_COUNT`; sessions and BIDS exports record which scale was used.
- **Input-referred noise.** Measure it with shorted inputs (through a resistor near electrode-skin
  impedance). In-band power of a scalp recording is not instrument noise. The experimental routes
  can read your figure from a rig profile (`OLIMEX_RIG_PROFILE`, see [`experimental.md`](experimental.md)).
- **Timing.** The bridge measures the sample-rate error; it does not measure latency or jitter
  between a stimulus and the recording.
- **Impedance.** The signal-plausibility check does not measure electrode impedance.
- **Lost samples.** The bridge counts malformed lines and timestamp gaps and records them with
  each session; the rate measurement assumes none were lost.

Keep what you measure with your own research records, citing the tool version you ran
(see [`versioning.md`](versioning.md)).
