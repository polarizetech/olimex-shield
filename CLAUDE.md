@AGENTS.md

# CLAUDE.md — olimex-shield

Arduino + Olimex SHIELD-EKG-EMG → bridge → workbench. MIT and public, so **nothing personal ever
enters this repo**: no subject names, no recordings, no keys, no names of private repos.

## Layout

- `apps/olimex-shield/`: the flashed sketch and the hardware setup guide.
- `apps/server/`: the bridge (`serve.py`, default port 8140, bound to 127.0.0.1): **acquisition**
  (owns the serial port), **trust in the reading** (`quality.py` signal-plausibility check,
  `timebase.py` measured rate, `rig.py` constants), **durability** (`durability.py`), the
  **session store** (`sessions.py`), the **upload hand-off** (`storage.py`, plugin only), **BIDS
  export** (`bids.py`) and the **experimental** routes (`experimental.py`).

  Detailed history and rules: `apps/server/CLAUDE.md`, `RIG.md`, `DURABILITY.md`, `INTEGRATION.md`.
- `apps/web/`: the workbench (`serve.py`, default port 8150). `signal-panel/` is the
  `<signal-panel>` component (and `<signal-panel-atlas>`); `placement/` draws electrode diagrams;
  `vendor/design/` is a synced copy of the design system and is never edited here.
- `docs/`: user-facing docs. `EXPERIMENTS.md` and `docs/versioning.md`: preregistration and the
  measuring-chain version.

## Core and experimental

Core follows established practice for EEG/ECG/EMG acquisition, or says plainly where it doesn't.
Anything that is not established (lock-in extraction, noise budgets, detection curves, the atlas,
nV noise floors, the alpha-SNR heuristic) is **experimental**: it lives in `experimental.py` or behind
a "beta" badge, is listed in `docs/experimental.md`, and core never depends on it. General-purpose
analysis belongs in the optional companion tools found via `$OLIMEX_TOOLS`, not here. Without them,
those features switch off.

## Versioning and preregistration

The measuring chain (see `docs/versioning.md`) is versioned by `pyproject.toml` and tagged
`model-vX.Y.Z` whenever a change alters a recorded or exported number. A new claim about the rig is a
preregistered experiment under `experiments/`, following `.agents/protocols/PREREG_PROTOCOL.md`.

## The blog post

The repo is described in the Polarize.Tech post *Can a $70 board tell me I'm wrong?*
(`_posts/2026-08-25-can-a-70-dollar-board-tell-me-im-wrong.md` in the polarize.tech site repo). The
README's rig photos come from that post. **The repo and the post must not contradict each other.**
`python3 scripts/check_blog.py` compares the facts they share and the photos. When a change here
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
- **The µV scale is not externally calibrated.** It comes from the shield's built-in cal signal at
  its nominal amplitude; say so wherever a µV or nV figure appears.
- **Stdlib only** for anything on the recording path. Optional dependencies are lazy imports.
- **Never play audio through the main output** when verifying anything.
- **Commit author** is `Joshua Anderton <info@joshanderton.com>`.
