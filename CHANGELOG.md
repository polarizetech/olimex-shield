# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Changes to the flashed sketch are listed
under **Board** so a recording can be matched to the firmware it was made with.

## [Unreleased]

## [0.2.0] — 2026-09-25

First public release. Tagged `model-v0.2.0`: this version changes numbers in recordings and exports,
so results from 0.1.0 are not comparable without saying so. No preregistered experiments existed
before it, so none is invalidated.

### Changed (measuring chain)
- The signal check is readout-aware and called a **signal-plausibility heuristic**, not a contact
  or impedance check. ECG and EMG are no longer judged by EEG rules (alpha SNR, the 100 µV floor).
  Band estimates use a Hann window, with non-overlapping band edges.
- µV per count (7.9) is labelled with its real provenance: the shield's built-in cal signal at
  nominal amplitude, not externally checked. The circular "independently recovered" claim is gone.
- BIDS: `PowerLineFrequency` from the session, not a hard-coded 60 Hz; ECG/EMG channels typed
  correctly; `ScalingProvenance`, `StreamIntegrity`, `SoftwareVersions`; a root README; synthetic
  and real sessions never share a dataset root.
- The bridge parses the board's `t_us` column, counts malformed lines and timestamp gaps (handling
  the `micros()` wrap), and writes `t_us` into its own recording.
- The EEG montage puts the active electrode at Oz (not the inion). The EMG montage is a SENIAM
  bipolar pair on the muscle belly.

### Added
- `apps/server/experimental.py`: every experimental route, marked `"experimental": true`, and
  "beta — experimental" badges in the workbench. See `docs/experimental.md`.
- KIT Adaptive Preregistration (`core`, `prereg`), `EXPERIMENTS.md` and `docs/versioning.md`.
- Sessions record `software_version` and `mains_hz`.
- `scripts/check_docs.py`: the README's safety list matches the workbench, and the blog post's
  shared figures and photos match this repo.

### Fixed
- The bridge bound to all interfaces and answered any web origin by default. It now binds
  127.0.0.1 and answers only loopback origins (or `$OLIMEX_ALLOWED_ORIGINS`).
- The signal panel's readout row never rendered. The rate row now says **declared** and shows the
  measured rate separately.
- UI text no longer attributes the noise spread to electrode prep (it is unexplained), or calls a
  40 Hz ASSR "within reach" (it is not yet shown).

### Safety
- The list now covers unplugging every mains-connected device, isolating the USB data line when not
  on battery, not touching grounded metal, and any current path across the chest.

### Board
- `eeg_stream.ino`: header comments only; the flashed behaviour is unchanged.

### Housekeeping
- ruff lint and format at line length 100, enforced in CI. References to the private repos this
  code came from are removed.

### Moved out (to optional companion tools, found via `$OLIMEX_TOOLS`)
- The Auditory Response Atlas, the extraction layer (lock-in, noise budget), injection curves and
  the acquisition-requirements checks. The workbench shows what depends on them only when they are
  present. This board's noise figures stayed here.
- The built-in S3 uploader was removed; `storage.py` is a plugin hand-off only.
- `quality.py` carries its own Goertzel helper so the contact check never depends on an optional tool.

### Fixed
- A plugin uploader was handed the live session folder, so an earlier upload's `uploads.json`
  receipt went into the snapshot. It now gets a staged copy holding exactly the manifest's files.

### Verified
- Live upload of a synthetic session to S3-compatible storage through a plugin. Every object's ACL
  was private, and every object refused a request made with no credentials (HTTP 403). The test
  objects were deleted afterwards.

### Changed
- Copyright holder is Polarize.Tech (LICENSE, CITATION.cff, pyproject.toml).

## [0.1.0] — 2026-09-15

First release as its own repository. The code was extracted from earlier internal tools.

### Added
- `apps/web`: the workbench. Live view with the Atlas tab, recording and tagging, playback
  against the tag track, electrode placement guide, uploads, BIDS export.
- `apps/server/storage.py`: private uploads to S3-compatible storage (DigitalOcean Spaces, AWS,
  MinIO) or a plugin, checked from outside with an anonymous read.
- `apps/server/bids.py`: stdlib EEG-BIDS export (BrainVision), verified by reading it back with
  MNE-BIDS.
- `apps/server/timebase.py`: the bridge measures the board's real sample rate against the host
  clock.
- `sessions.annotate()`: adds the measured rate to a finished session without rewriting it.

### Fixed
- The recording panel dropped the last partial batch at Stop: 1859 samples stored against 2020
  in the black box on the real board. Samples buffered while the store opened were also lost,
  and appends could race each other. Now contiguous and ordered, verified as an exact slice of
  the black box.
- Every recording's black box was written to `capture.csv`, overwriting the previous one. Each
  now gets its own name.

### Board
- `eeg_stream.ino` is unchanged from the version checked against the live board on 2026-09-14.
