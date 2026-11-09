@AGENTS.md

# CLAUDE.md — olimex-shield

**Kind:** tool (`TOOL.toml`). Acquires, checks, records and exports EEG/ECG/EMG from an Arduino +
Olimex SHIELD-EKG-EMG.

Arduino + Olimex SHIELD-EKG-EMG → bridge → workbench. MIT and public, so **nothing personal ever
enters this repo**: no subject names, no recordings, no keys, no names of private repos.

## Layout

- `apps/olimex-shield/`: the flashed sketch and the hardware setup guide.
- `apps/server/`: the bridge (`serve.py`, default port 8140, bound to 127.0.0.1): **acquisition**
  (owns the serial port), **trust in the reading** (`quality.py` signal-plausibility check,
  `timebase.py` measured rate, `rig.py` constants), **durability** (`durability.py`), the
  **session store** (`sessions.py`), the **upload hand-off** (`storage.py`, plugin only), **BIDS
  export** (`bids.py`) and the **extension kit** (`extensions.py`).

  Detailed history and rules: `apps/server/CLAUDE.md`, `DURABILITY.md`, `INTEGRATION.md`.
- `apps/web/`: the workbench (`serve.py`, default port 8150). `signal-panel/` is the
  `<signal-panel>` component (and `<signal-panel-atlas>`); `placement/` draws electrode diagrams;
  `vendor/design/` is a synced copy of the design system and is never edited here.
- `extensions/`: extensions built on the bridge, versioned apart. `catalog.json` lists them,
  `_template/` is a valid example, `experimental/` holds the experimental analysis routes.
- `tests/test_contract.py`: the version, the catalogue, the extensions and the import direction.
- `docs/`: user-facing docs, listed in `docs/INDEX.md`. `docs/versioning.md`: releases and tags.

## Scope

**What this tool does:** acquires one channel from the board over USB, checks whether the signal
is plausible, measures the real sample rate, records durably, plays back, and exports EEG-BIDS.
Core follows established practice for EEG/ECG/EMG acquisition, or says plainly where it doesn't.

**What this tool does not hold:** research. No questions, experiments, results or findings, no
measurements of any particular board (noise floors, rate errors, validation runs), no
`EXPERIMENTS.md`, `experiments/` or `RESEARCH.md`. A number produced with this tool is a finding of
the research repo that produced it, recorded there against the release it used. General-purpose
analysis is not here either.

### Moved out

Recorded so nobody puts it back.

| What | Moved to | When | Why |
|---|---|---|---|
| Measurements of one board, validation write-ups, the experiment registry (`EXPERIMENTS.md`, `RIG.md`, `validation/`) | the maintainer's research repo (the `olimex-shield-bridge` consumer in `TOOL.toml`); the blog post publishes results | 2026-09-27 | findings belong to the research that made them |
| General-purpose analysis: the auditory atlas, lock-in extraction, noise budgets, injection curves, the rate/carrier firewall, `bioacq`, uploads | optional companion tools found via `$OLIMEX_TOOLS`; without them those features switch off | 2026-09-16 | not specific to this board |
| The experimental routes (`apps/server/experimental.py`) | the extension `extensions/experimental/` (`olimex-shield-ext-experimental`) | 2026-09-27 | core never depends on experimental code |

## Consumers

Listed in `TOOL.toml` under `[[consumers]]`, each with `uses`: the routes, constants, files and
formats it relies on. A change to one of those is a change for that consumer even when every test
here passes: name it under `### Outputs changed` in `CHANGELOG.md`. Consumers pin a `vX.Y.Z` tag.

## Extensions and experimental features

- Anything not established (lock-in extraction, noise budgets, detection curves, the atlas, nV
  noise floors) is **experimental**: it lives in an extension or behind a "beta" badge, is listed
  in `docs/experimental.md`, and core never depends on it. The alpha-SNR heuristic in
  `quality.py` is flagged experimental in its responses.
- An extension is its own package under `extensions/<name>/` (or another repo), named
  `olimex-shield-ext-*`, with its own version, changelog and gate, and a declared range of this
  tool's releases (`>=X.Y.0,<X.Y+1`). It calls `extensions.declare()` and serves routes through
  `ROUTES` (`docs/EXTENSIONS.md`).
- **The arrow runs one way.** No core file (`apps/server`, `apps/web`, `scripts`) imports an
  extension; the bridge reaches them only through `extensions.discover()` and
  `extensions.route_table()`. `tests/test_contract.py` asserts it by AST.
- Every extension found is reported in `/health` with a status; none is dropped silently. A
  catalogued route whose extension is not loaded answers 503 with that status.
- In-repo extensions are catalogued in `extensions/catalog.json`; the contract tests hold the
  catalogue, the folders, `pyproject.toml`, `declare()` and `ROUTES` to each other.

## Releases

Follow `.agents/protocols/TOOL_VERSIONING.md` (installed with the kit's `tool-versioning` module;
until then `docs/versioning.md` states it):

- **One version**: `version` in `pyproject.toml`, mirrored in `CITATION.cff` and `TOOL.toml`, with
  a `## [X.Y.Z] — date` heading in `CHANGELOG.md`. The contract tests fail otherwise.
- **Any change to an output bumps MINOR** and gets `### Outputs changed`, naming the consumers to
  re-run. A release with no output change leaves the section out. PATCH never changes an output.
- **Tags are `vX.Y.Z`** (annotated, dated, never moved). Releases up to 0.2.0 were `model-v*`.
- A minor bump refuses every extension until its gate is re-run and its range widened (with
  `extensions/_template/`). Don't tag or push without being asked.

## The blog post

The repo is described in the Polarize.Tech post *Can a $70 board tell me I'm wrong?*
(`_posts/2026-08-25-can-a-70-dollar-board-tell-me-im-wrong.md` in the polarize.tech site repo). The
README's rig photos come from that post. **The repo and the post must not contradict each other.**
`python3 scripts/check_docs.py` compares the spec facts they share and the photos. When a change here
makes the post wrong, update the post in the same piece of work (pushing the site is publishing: ask
first).

## Run and test

```bash
python3 apps/web/serve.py        # starts a bridge if none answers
python3 scripts/check.py         # every suite
```

## Rules that do not relax

- **Safety** text is shown in full before any port opens, and never condensed. The README repeats
  it word for word.
- **Synthetic never looks measured.** The tier comes from `status.demo`, not the port name.
- **The browser draws; the server computes** every number.
- **Sessions, recordings and exports stay out of git.** Uploads are private and are checked with
  an anonymous read.
- **Declared vs measured sample rate** are different numbers and are labelled as such everywhere.
- **The µV scale is not externally calibrated.** The default (7.9) comes from one board's built-in
  cal signal at its nominal amplitude and is overridable (`$OLIMEX_UV_PER_COUNT`); say so wherever
  a µV or nV figure appears.
- **This repo is the tool only.** Measurements, validation results and experiment records about
  any board go in the research repo, not here; the blog post publishes them.
- **Core never imports an extension**, and never depends on experimental code.
- **Stdlib only** for anything on the recording path. Optional dependencies are lazy imports.
- **Never play audio through the main output** when verifying anything.
- **Commit author** is `Joshua Anderton <info@joshanderton.com>`.
