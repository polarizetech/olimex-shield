# Standards: what this repo meets, and what it is working toward

Each row says what exists today and names the next concrete step. "Planned" means not built.

## In place

| Standard | Where | Status |
|---|---|---|
| **EEG-BIDS 1.9.0** (BrainVision) | `apps/server/bids.py` | Built. The test suite reads exports back with MNE-BIDS and compares every sample. **Not yet run through the official `bids-validator`.** |
| **Scientific Python repo layout** ([sp-repo-review](https://learn.scientific-python.org/development/guides/repo-review/)) | `pyproject.toml`, `LICENSE`, `CITATION.cff`, `CHANGELOG.md`, `CONTRIBUTING.md`, CI | Partial. There is no `src/` package or `pytest` suite: the checks are self-contained `dev_check.py` scripts so a stdlib-only machine can run them. No PyPI release. |
| **Correctness lint** (ruff: pyflakes, bugbear) | `pyproject.toml` | Clean. |
| **Firmware builds in CI** | `.github/workflows/ci.yml` | Compiles for `arduino:avr:uno`. It cannot check what is flashed on your board; the streaming check in `apps/olimex-shield/README.md` does that. |

## Planned

### Lab Streaming Layer (LSL) and XDF

LSL is the standard way to time-align several devices. One example is this ECG beside a phone
magnetometer.

- **Next step:** a `pylsl` outlet in the bridge that publishes the sample stream with the host
  timestamp it already takes for `timebase.py`. Recording would be done with LabRecorder to XDF.
- **Validate** the way the LSL project does: send one hardware pulse into both streams and
  measure the offset. Until that pulse test is run, any claim that two streams are aligned is
  untested.

### NeuroKit2 benchmark for ECG

NeuroKit2 publishes benchmarks for R-peak detection. This repo does not detect R peaks yet.

- **Next step:** if an ECG readout gains heart-rate analysis, use `nk.ecg_peaks` and report its
  published sensitivity and positive predictivity beside results from this board. Do not write a
  new detector.

### MNE data objects and per-session QC reports

BIDS exports already open in MNE.

- **Next step:** an `mne.Report` per session containing:
  - the raw trace;
  - the PSD, showing the analog band and mains;
  - the contact verdict from `/quality`;
  - the measured sample rate.

### A device-validation write-up (after Krigolson et al., 2017)

Krigolson et al. validated a consumer EEG headset (the Muse) by recovering known ERP components
against published values. The same shape of study for this board:

1. Record a positive control whose answer is known, on this board and on a reference amplifier at
   the same time:
   - a 40 Hz auditory steady-state response;
   - an N1/P2 to tones;
   - eyes-closed alpha.
2. Report the agreement, the noise floor (`apps/server/validation/VALIDATION.md` already has it:
   median 157 nV at 40 Hz over 60 s; corrected 2026-09-13 from 238) and the measured clock error.
3. Pre-register the analysis as an experiment (see [`versioning.md`](versioning.md)).

**Nothing here has yet recorded a response to a known stimulus.** The noise is characterised;
detection is not shown.

### JOSS / pyOpenSci review

Both review checklists ask for:

- an installable package;
- documented functionality with examples;
- automated tests;
- a statement of need;
- community guidelines.

The last three exist. The package and the statement of need do not.

## Not applicable here

**Motion-BIDS** (including its `MAGN` magnetometer channel type) is for motion and phone sensor
recordings. It applies to a phone magnetometer recorder, not to this board.
