# Experimental features

Everything in this repo falls into one of two groups:

- **Core** is acquisition, contact checks, sample-rate measurement, recording, playback and BIDS
  export. It follows established practice, or states plainly where it doesn't.
- **Experimental** is analysis we find useful that is **not yet an established method** for this
  kind of hardware. It may change or disappear, and it has not been validated against a reference
  amplifier.

Experimental features carry a **beta — experimental** badge in the workbench, and every response
from an experimental bridge route includes `"experimental": true` and a `note`. Their server code
lives in [`apps/server/experimental.py`](../apps/server/experimental.py). Nothing in core depends on
them.

## Using them

They are off unless the optional companion analysis tools are installed. Point the bridge at them:

```bash
export OLIMEX_TOOLS=/path/to/tools
python3 apps/web/serve.py
```

Without them, those routes answer `503 not installed` and the workbench hides what depends on them.

## What counts as experimental

| Feature | Why it is experimental |
|---|---|
| Lock-in extraction, integration check, noise budget, detection curves | Novel use on a 10-bit, uncalibrated single channel |
| Auditory response atlas | Predictions from the literature, not measurements on this rig |
| Rig noise floors in nV (`experimental.MEASURED_RIG`) | Depend on the uncalibrated µV-per-count scale; spread unexplained |
| Alpha-SNR part of the signal-plausibility check (EEG only) | A heuristic, not an impedance measurement |
| Client-side `bands()` and `iaf()` (`eeg-client.js`) | Deprecated; the server computes these |

If you use any of these in a write-up, say that it is experimental and cite the version you ran
(see [`versioning.md`](versioning.md)).
