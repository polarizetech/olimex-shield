# Experimental features

Everything in this repo falls into one of two groups:

- **Core** is acquisition, contact checks, sample-rate measurement, recording, playback and BIDS
  export. It follows established practice, or states plainly where it doesn't.
- **Experimental** is analysis we find useful that is **not yet an established method** for this
  kind of hardware. It may change or disappear, and it has not been validated against a reference
  amplifier.

Experimental features carry a **beta — experimental** badge in the workbench, and every response
from an experimental bridge route includes `"experimental": true` and a `note`. Nothing in core
depends on them.

## The experimental extension

Their server code is an **extension**, `olimex-shield-ext-experimental`, in
[`extensions/experimental/`](../extensions/experimental/): its own package, its own version and
[changelog](../extensions/experimental/CHANGELOG.md), and a declared range of olimex-shield
releases it was tested against. The bridge never imports it by name. At start-up the extension kit
(`apps/server/extensions.py`) finds it through [`extensions/catalog.json`](../extensions/catalog.json)
(no install needed), checks its range, and serves the routes it exposes. How that works, and how
to write another, is in [`EXTENSIONS.md`](EXTENSIONS.md).

`GET /health` lists it under `extensions` with a status:

| Status | Meaning | Its routes answer |
|---|---|---|
| `ok` | Loaded, and tested against this release | normally (503 "not installed" without the companion tools) |
| `incompatible` | This olimex-shield release is outside the range it declares | 503, with the extension's status and why |
| `undeclared` / `error` | It did not declare itself, or failed to import | 503, with the extension's status and why |

Its `health` entry says which companion tools it found (`atlas`, `detection`, `toolsDir`) and
whether a rig profile is configured. A new minor release of olimex-shield refuses the extension
until its gate (`python3 extensions/experimental/dev_check.py`) is re-run and its range widened.

## Using them

They are off unless the optional companion analysis tools are installed. Point the bridge at them:

```bash
export OLIMEX_TOOLS=/path/to/tools
python3 apps/web/serve.py
```

Without them, those routes answer `503 not installed` and the workbench hides what depends on them.

## Your rig profile

The noise budget and detection curves need a noise floor for **your** board. This tool ships none:
a noise floor is a measurement of one board, and belongs with your research records. Give it per
request (`noise_floor_uv_rms`, `provenance`), or once in a JSON file:

```bash
export OLIMEX_RIG_PROFILE=/path/to/my-rig.json
```

```json
{
  "noise_floor_uv_rms": 2.0,
  "provenance": "MEASURED",
  "uv_per_count": 7.9,
  "how_measured": "shorted inputs through a resistor, 5 min, 1-40 Hz",
  "notes": "anything else; kept and echoed back"
}
```

| Field | Required | Meaning |
|---|---|---|
| `noise_floor_uv_rms` | yes | In-band noise floor in µV RMS, positive. |
| `provenance` | no | `MEASURED`, `DATASHEET` or `RECALLED-VERIFY` (the default). Only `MEASURED` lets the noise budget return a verdict. |
| `uv_per_count` | no | The scale the floor was measured with; used when a request gives none. |
| other keys | no | Kept and echoed back unchanged. |

The values above are placeholders, not a board's figures. A figure in the request wins over the
profile, and each answer says which it used (`noise_floor_basis`). The file is re-read on every
request. With neither, `/noise-budget` and `/detection-curve` answer `400` saying no rig profile is
configured. `GET /rig/profile` (and `/extract/reference` → `rigProfile`) report what is
configured, or why a file was refused; `/rig/profile` needs no companion tool.

## What counts as experimental

| Feature | Why it is experimental |
|---|---|
| Lock-in extraction, integration check, noise budget, detection curves | Novel use on a 10-bit, uncalibrated single channel |
| Auditory response atlas | Predictions from the literature, not measurements on this rig |
| Rig noise floors from a rig profile (`$OLIMEX_RIG_PROFILE`) | User-supplied; they inherit whatever µV-per-count scale they were measured with |
| Alpha-SNR part of the signal-plausibility check (EEG only) | A heuristic, not an impedance measurement |
| Client-side `bands()` and `iaf()` (`eeg-client.js`) | Deprecated; the server computes these |

If you use any of these in a write-up, say that it is experimental and cite the version you ran
(see [`versioning.md`](versioning.md)).
