# Versioning

A recording is only as trustworthy as the chain that made it: the flashed sketch, and the numbers the
bridge computes from it. This tool has one version, and any result obtained with it should name
that version's tag.

The rules are KIT Adaptive Preregistration's `TOOL_VERSIONING` protocol
(`.agents/protocols/TOOL_VERSIONING.md` once the kit's `tool-versioning` module is installed here;
source: <https://github.com/polarizetech/adaptive-preregistration>). This page says how they apply
to olimex-shield.

## The measuring chain

These files decide what a recording or an export contains:

| Part | Files |
|---|---|
| Firmware | `apps/olimex-shield/eeg_stream/eeg_stream.ino` |
| Scaling and rig constants | `apps/server/rig.py` |
| Signal-plausibility check | `apps/server/quality.py` |
| Sample-rate measurement | `apps/server/timebase.py` |
| Stored and exported data | `apps/server/serve.py` (black box), `apps/server/sessions.py`, `apps/server/bids.py` |

The workbench's drawing code, docs and tests are not part of the chain. Neither are extensions:
they are versioned apart (see [`EXTENSIONS.md`](EXTENSIONS.md)), and the numbers of the
experimental one are not outputs until a feature is promoted to core.

## One version, tagged

- The version is `version` in `pyproject.toml`. `CITATION.cff` (`version`, `date-released`) and
  `TOOL.toml` (`version`) mirror it, and `CHANGELOG.md` has a `## [X.Y.Z] — YYYY-MM-DD` heading
  for it. Code reads it from `pyproject.toml` (`sessions.software_version()`); nothing else
  hard-codes it. `tests/test_contract.py` fails when any of these disagree.
- SemVer, `0.MINOR.PATCH` before 1.0. **Any change to an output bumps MINOR.** An output is any
  number or field the tool records or exports, a default constant (the µV per count, the declared
  rate, a threshold), a unit, an algorithm, or a file layout a consumer parses (the black-box CSV,
  `session.json`, the BIDS files). PATCH releases never change an output.
- Every release is an annotated tag `vX.Y.Z` with its date in the message, on the release commit,
  never moved or deleted. A mistake is fixed with a new version.
- Releases up to 0.2.0 were tagged `model-vX.Y.Z` (`model-v0.2.0`). From 0.3.0 on the tag is
  `vX.Y.Z`.

## A release that changes an output says so

Its `CHANGELOG.md` entry has an `### Outputs changed` section: each changed function, route,
field or constant, the old and new behaviour, and which consumers must re-run (or "none"). A
release that changes no output leaves the section out. Firmware changes are listed under
**Board**, so a recording can be matched to the sketch that made it.

Every session records the version that made it (`software_version` in `session.json`), and BIDS
exports carry it in `SoftwareVersions`, so a recording can be matched to its tag.

## Consumers pin a tag

A repo that depends on this tool pins a tag (`@v0.3.0`, or a submodule at the tag), never a
branch, and its results cite that tag. The known consumers, and exactly what each relies on, are
listed under `[[consumers]]` in [`TOOL.toml`](../TOOL.toml). A change to anything listed there is a
change for that consumer even when every test here passes, and the release names it.

## Experiments about a rig live in your research repo

This repo is the tool. It holds no experiments, measurements, validation results or experiment
records about any board: no `EXPERIMENTS.md`, no `experiments/`.

A claim about a rig, such as its noise floor, timing jitter or a recovered evoked response, is an
experiment about that rig. Preregister it and record it in your own research repo (one that
follows the kit's `PREREG_PROTOCOL`):

1. Write the preregistration with numeric predictions and pass/fail thresholds, citing the
   `vX.Y.Z` tag of this tool it runs against.
2. Freeze it (commit and tag it) **before** recording or analysing any data.
3. Run it, and write the results against the frozen thresholds.

A failed prediction closes that experiment; retrying means opening a new one. When a new release
changes a number your experiment depends on, its `### Outputs changed` section says so.

## Releasing

1. `CHANGELOG.md`: move `[Unreleased]` under `## [X.Y.Z] — YYYY-MM-DD`, with `### Outputs changed`
   if any output changed, naming the consumers to re-run.
2. Bump `pyproject.toml`, `CITATION.cff` (`version`, `date-released`) and `TOOL.toml` in the same
   commit. A minor bump refuses every extension until its gate is re-run and its range widened.
3. `python3 scripts/check.py` (it includes the contract tests), and
   `python3 .agents/tools/release-check` once the kit's `tool-versioning` module is installed.
4. `git tag -a vX.Y.Z -m "YYYY-MM-DD <summary>"`, then push the commit and the tag.
5. Tell the consumers listed under `### Outputs changed`.
