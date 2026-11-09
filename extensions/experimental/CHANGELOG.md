# Changelog — olimex-shield-ext-experimental

Format: [Keep a Changelog](https://keepachangelog.com/). This extension is versioned apart from
olimex-shield and declares the olimex-shield releases it was tested against (`REQUIRES`).
Everything it serves is experimental: its numbers are not outputs of olimex-shield under
`.agents/protocols/TOOL_VERSIONING.md` §7.

## [0.1.0] — 2026-09-27

Tested against olimex-shield 0.3.0 (`REQUIRES = ">=0.3.0,<0.4"`).

### Added
- The experimental routes that were `apps/server/experimental.py` in olimex-shield 0.2.0, as an
  extension: `GET /claims`, `/atlas/reference`, `/extract/reference`, `/rig/profile`;
  `POST /predict`, `/montage`, `/simulate`, `/integration-check`, `/extract`, `/extract/sustain`,
  `/extract/artifact`, `/extract/feasibility`, `/noise-budget`, `/detection-curve`, `/rate-trade`.
  URLs, request fields, responses and the `"experimental": true` + `note` marking are unchanged.
- `health()`: which companion tools were found, for the bridge's `/health`.
