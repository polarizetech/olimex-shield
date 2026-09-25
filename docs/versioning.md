# Versioning

A recording is only as trustworthy as the chain that made it: the flashed sketch, and the numbers the
bridge computes from it. That chain has one version, and any claim about the rig names the version it
was tested against.

## The measuring chain

These files decide what a recording contains. The protocol calls this the "model".

| Part | Files |
|---|---|
| Firmware | `apps/olimex-shield/eeg_stream/eeg_stream.ino` |
| Scaling and rig constants | `apps/server/rig.py` |
| Contact check | `apps/server/quality.py` |
| Sample-rate measurement | `apps/server/timebase.py` |
| Stored and exported data | `apps/server/sessions.py`, `apps/server/bids.py` |

The workbench's drawing code, docs and tests are not part of the chain.

## Tags

- The version is `version` in `pyproject.toml`, mirrored in `CITATION.cff`.
- Any change to the chain that alters a number in a recording or an export bumps the version and is
  tagged `model-vX.Y.Z`. Examples: sample cadence, µV per count, contact thresholds, BIDS fields.
  Any other change needs no tag.
- `CHANGELOG.md` lists, for each chain version, which experiments in
  [`EXPERIMENTS.md`](../EXPERIMENTS.md) it invalidates. Firmware changes stay under **Board**.
- Every session records the version that made it (`software_version` in `session.json`), and BIDS
  exports carry it in `SoftwareVersions`, so a recording can be matched to its tag.

## Claims about the rig are predicted first

A new claim about the rig, such as its noise floor, timing jitter or a recovered evoked response, is a
preregistered experiment:

1. Write `experiments/<EID>/PREREG.md` with numeric predictions and pass/fail thresholds, naming the
   `model-v*` tag it runs against.
2. Commit it and tag `<EID>-prereg` **before** recording or analysing any data.
3. Run, write `RESULTS.md` against the frozen thresholds, then tag `<EID>-run` and `<EID>-closed`.

A failed prediction closes that experiment. Retrying means opening a new one. Only aggregate statistics
are committed: raw recordings of people never enter this repo.
