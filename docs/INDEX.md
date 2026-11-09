# Documentation

At the root of this repo only `README.md` and `CLAUDE.md` are documentation; the other root files
are there because tooling expects them (`AGENTS.md`, `CHANGELOG.md`, `CITATION.cff`, `LICENSE`,
`TOOL.toml`, `pyproject.toml`, `CONTRIBUTING.md`). User-facing documents live here:

| Document | What it covers |
|---|---|
| [`hardware.md`](hardware.md) | The board's specification, and what to measure on your own board |
| [`recording.md`](recording.md) | Recording, playback, uploads and BIDS export |
| [`standards.md`](standards.md) | The standards followed, and the roadmap |
| [`versioning.md`](versioning.md) | Releases, tags, what counts as an output change, and how to cite a version |
| [`experimental.md`](experimental.md) | Experimental features, the experimental extension, and the rig profile |
| [`EXTENSIONS.md`](EXTENSIONS.md) | How to build on olimex-shield: the extension contract and its versioning rule |

Documents that belong to one part of the code live beside it:

| Document | What it covers |
|---|---|
| [`apps/olimex-shield/README.md`](../apps/olimex-shield/README.md) | Flashing the sketch, wiring, checking your board |
| [`apps/server/README.md`](../apps/server/README.md) | The bridge: running it, its routes |
| [`apps/server/INTEGRATION.md`](../apps/server/INTEGRATION.md) | Writing a client of the bridge |
| [`apps/server/DURABILITY.md`](../apps/server/DURABILITY.md) | How a session is kept from being lost |
| [`apps/web/signal-panel/INTEGRATION.md`](../apps/web/signal-panel/INTEGRATION.md) | Embedding `<signal-panel>` |
| [`apps/web/placement/INTEGRATION.md`](../apps/web/placement/INTEGRATION.md) | The electrode placement diagrams |
| [`extensions/experimental/CHANGELOG.md`](../extensions/experimental/CHANGELOG.md) | The experimental extension's releases |
