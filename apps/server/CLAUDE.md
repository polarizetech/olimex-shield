# CLAUDE.md — apps/server (the olimex-shield bridge)

The one process that holds the board's serial port, and the tooling that says whether what comes
through it can be trusted.

What this process owns:

1. **Acquisition** — the serial port, a ring buffer, SSE, a black-box recorder (`serve.py`), and a
   count of what the wire lost (`timebase.StreamIntegrity`).
2. **Trust in the reading** — the signal-plausibility check (`quality.py`) and the measured sample
   rate (`timebase.py`), plus the board's constants (`rig.py`).
3. **Durability** (`durability.py`, `DURABILITY.md`) — a session must never be lost, and a partial
   one must never look complete.
4. **Sessions** (`sessions.py`), **upload hand-off** (`storage.py`, plugin only) and **BIDS export**
   (`bids.py`).

**Experimental analysis is siloed in `experimental.py`.** Lock-in extraction, the integration
check, the noise budget, detection curves, the rate trade and the auditory atlas are not
established methods for this hardware. They come from optional companion tools
(`signal-detection`, `auditory-atlas`, `injection-recovery`) found through `$OLIMEX_TOOLS` (or a
tools directory with a `REGISTRY.md` above this repo). Without them those routes answer 503 "not
installed". **Every response from them carries `"experimental": true` and a `"note"`**, 503s
included. The rig's nV noise figures (`MEASURED_RIG`, `NOISE_NV_AT_40HZ`) and the `RECALLED` table
live there too. See `docs/experimental.md`.

**The daemon measures the sample rate itself** (`timebase.py`, 2026-09-15). The board's clock says
250 Hz; against the host clock it runs ~−680 ppm and drifts (−644 → −685 ppm in one day).
`/status` keeps `rate: 250` as the **declared** value and adds `rateMeasured` / `rateErrorPpm` /
`rateUncertaintyPpm` / `rateBasis`, `null` for the first 30 s. Method and validation: `RIG.md`.

Stdlib-only except an optional `pyserial`. Must still run on Python 3.9.

Run: `python3 apps/server/serve.py [PORT] [BIND]` (default 8140 127.0.0.1). Usually the workbench
starts it. Tests: `python3 apps/server/dev_check.py` (plus `dev_check_sessions.py`,
`dev_check_storage.py`).

---

## Why the acquisition half exists (the load-bearing constraint)

**Only one process may hold the serial port.** The daemon originally lived inside an earlier
internal app; any second project wanting the signal had to fight for the device or duplicate the
reader. This extracts it so there is exactly one owner and many clients. If another process is
holding the port, close it there before opening here — they cannot coexist.

## Architecture (carried over from that app, which proved it — don't regress these)

- **The server owns the port, not the browser.** A browser reload kills a Web Serial read loop and
  takes the acquisition with it. Here the reader thread survives; a reattaching client resumes from
  its last sample index. Acquisition never stops.
- **Ring buffer + monotonic `total`.** A client that falls behind the ring can detect the gap
  (`read_since` returns `actual_from`, and the client counts `gaps`).
- **`/open` is idempotent** (same port+baud already running → no-op). A reload must NOT reopen/reset
  the device.
- **`generation`** bumps on each (re)open so a client can detect a device swap and reset its ring.
- **Black-box recorder**: when armed, every sample the reader pulls is appended to disk *independent
  of any browser*, flushed each write and fsynced every ~3 s — a tab/OS crash still leaves a
  complete raw capture. Columns are `sample_index,value,t_us` (older files lack `t_us`;
  `read_black_box()` reads both), and a trailing `# stopped …` line records what the wire lost.
- **CORS is an allow-list.** Sibling apps on other *local* ports must be able to consume the feed,
  so the `Origin` is echoed back when it is `http://127.0.0.1:<port>`, `http://localhost:<port>`
  or `http://[::1]:<port>`, or listed in `$OLIMEX_ALLOWED_ORIGINS` (comma-separated). Never `*`:
  any web page the operator had open could otherwise read their physiology.
- **Degrades gracefully**: no pyserial → service still runs, reports `supported:false`, clients fall
  back. No companion tools → the experimental routes 503; acquisition is unaffected.

## The stream is checked, never repaired (2026-09-25)

The reader parses each line **positionally**: column 0 is `t_us`, `channelCol` the value. A line
that fails is **dropped and counted** (`parseErrors`); nothing is ever inserted in its place. The
old parser skipped non-numeric tokens, which shifted columns — a garbled `t_us` silently turned ch1
into ch0. `StreamIntegrity` then reads the board's own `t_us`: a step more than 1.5× the declared
period is a **gap** (with `max_gap_us` and a `missing_estimate`), a backwards jump is a
**clock reset** (the board rebooted), and the 32-bit `micros()` wraparound (~71.6 min) is handled
by modular arithmetic. `/status` carries `parseErrors`, `streamGaps`, `maxGapUs` and the full
record under `stream`; `/record/stop` returns `recParseErrors` / `recGaps` / `recMaxGapUs` for the
recording window, and the workbench annotates the session with them (`stream_*`), from where the
BIDS sidecar picks them up. `RateEstimator` assumes no samples are lost; a non-zero `streamGaps`
is the evidence that the assumption failed.

## The dependency runs one way, and `dev_check.py` asserts it

Experimental analysis may read the daemon's samples. **The daemon must never depend on it.**
`serve.py` imports `experimental.py` inside a guard, and `experimental.py` guards each tool import
with a stub exception class, so a tool that failed to import cannot make the request handler
`NameError` while handling an error. Acquisition is the job that is not allowed to fail.

---

## The front end lives in `apps/web`

`/scope` used to be a page served from here. That front end is now `<signal-panel>` in
`apps/web/signal-panel` (the Monitor tab). **The backend stays here:** `/quality`, `/bands`,
`/spectrum` and the SSE stream are this service's, and the UI is a client of them like anything
else.

### The contact check measures PLAUSIBILITY, not impedance

`quality.py` is ported from an earlier internal app, where the logic was trapped inside one browser
app. It is now stdlib Python beside the daemon, so the UI, a CLI, a sibling app and `dev_check.py`
all get the same answer. What it measures, stated exactly:

- **Readout-aware.** `readout` (top level, or `cfg.readout` — the panel forwards only `cfg`)
  selects the checks. **EEG** keeps the scalp amplitude floor (100 µV of SD) and the alpha ratio.
  **ECG, EMG and anything else** get only rails, mains share and a flat-line floor (SD at or below
  1.5 counts). A limb lead is never judged on alpha or on a scalp-EEG floor.
- **Hann-windowed, half-open bands.** Band estimates sum exact DFT bins in `[lo, hi)` after a Hann
  window, so adjacent bands never share a bin and the classic bands partition 1–45 Hz.
- **Wording.** Messages say what was measured ("flat/implausible signal — check contact"), never
  "high impedance" or "no scalp contact": nothing on this board measures impedance.
- **Response shape.** Every earlier key is kept. Added: `method: "plausibility heuristic"`,
  `readout`, `flat`, `mains_hz_basis`, and `alpha_snr_detail` (`value`, `applied`,
  `experimental: true`). The alpha ratio is experimental.
- **Mains.** A caller's `mains_hz` wins, then `$OLIMEX_MAINS_HZ`, then the bench default
  `rig.MAINS_HZ` (60), labelled as such in `mains_hz_basis`.

A channel near its own floor is measuring the room, and it will produce a plausible trace and an
empty result minutes later. Twenty seconds of pre-flight catches the obvious cases.

### Every number comes from the server

The browser draws; it does not compute. Reimplementing a band power in JS to save a round trip is
how two answers to the same question start disagreeing. The one exception is the **display
filter**, which is cosmetic, labelled as such on the page, and never feeds a readout.

`eeg-client.js` still carries `bands()` and `iaf()` because pages already call them. Both are
marked `@deprecated EXPERIMENTAL`; `bands()` now uses the server's method (Hann, sum of bins,
half-open bands) so its relative shares match `/bands`, and `iaf()` returns `null` unless the
maximum is a true local peak away from the 7–13 Hz edges.

### The synthetic source, and why it is loud

`demo://synthetic` generates plausible EEG — drifting 1/f background, a waxing alpha burst, mains,
occasional blinks — so the whole UI and every analysis path can be exercised with no hardware. It is
**a distinct port name, never a silent fallback from a failed open**; `status()` reports
`demo: true` with a warning string, and the page shows a **SYNTHETIC DATA** banner for as long as it
runs. It also emits a synthetic `t_us`, so the integrity path is exercised (and reports no gaps). It
is deliberately not a clean sinusoid: a demo that looks better than real data teaches the wrong
expectation about what a good channel looks like.

---

## Hardware

Arduino + **Olimex SHIELD-EKG-EMG**, CSV over serial (`t_us,ch0,ch1`), **115200 baud, ~250 Hz**.
`channelCol` selects the column (default 1 = ch0; 0 means "no `t_us` column"). Any board printing
CSV lines in that shape works. It is **one differential channel**.

**µV per count is 7.9, and it is not externally verified.** It was derived in an earlier internal
app from the shield's built-in calibration square wave at its nominal ~250 µV peak-to-peak
(250 / 31.6 counts). The datasheet gain implies 1.72. `rig.UV_PER_COUNT_PROVENANCE` says so, and
the BIDS sidecar carries it as `ScalingProvenance`. Every µV and nV figure in this repo inherits it.

## Data

`recordings/` holds raw black-box captures and is **gitignored** — physiological data stays local
unless deliberately committed elsewhere. Sessions go to `$OLIMEX_SESSIONS` (gitignored default
`<repo>/sessions`). Each `session.json` records `software_version` (from `pyproject.toml`) and
`mains_hz` (caller, else `$OLIMEX_MAINS_HZ`, else null).

## BIDS export (`bids.py`)

- `PowerLineFrequency`: the session's `mains_hz`, else `$OLIMEX_MAINS_HZ`, else `"n/a"` (BIDS 1.9
  allows it). Never the bench's 60 assumed.
- ECG/EMG stay in the `eeg` datatype (BIDS 1.9 has no standalone ECG/EMG datatype, and EEG-BIDS
  permits those channel types), typed truthfully with the matching `*ChannelCount` and a
  `RecordingNote`.
- Synthetic and real sessions never share a root: mixing is refused in both directions.
- A minimal `README` is written if the root has none; `License` and `Authors` go into
  `dataset_description.json` only when the caller supplies them.
- `SoftwareVersions` and `GeneratedBy[0].Version` carry the chain version.

## Honesty (applies to every consumer — see INTEGRATION.md §"Before you build a closed loop")

The bridge is a **read**. It validates nothing about what any app's audio is doing. Band power is a
noisy, artefact-prone proxy (jaw clench and blinks move alpha); one montage cannot localise;
baselines drift. A closed loop built on it is an inference chain — EEG → band power → "state" →
audio — and every arrow is an assumption. Live monitoring, raw recording and event timestamping are
solid uses. *Steering* audio from it is where the burden of proof begins, and conclusions stay
**[C]/[SPEC]** until artefact-rejected, baseline-controlled, ideally blinded.

The atlas (experimental) **predicts**; it measures nothing. Its most useful single output is
probably the artefact caveat: an FFR recorded through an unshielded transducer can be the
transducer, at exactly the frequency and exactly the waveform you were looking for.

## The extraction layer, run against THIS board's captures (EXPERIMENTAL)

`validation/rig_noise_floor.py` runs the noise-floor gate against this rig's own private captures.
It needs `$OLIMEX_RIG_CAPTURES` (never in this repo) and the companion signal-detection tool; it
reads and writes nothing else. Its figures are experimental and inherit the unverified µV/count.

- The **broadband RMS is the wrong quantity** for a lock-in: real EEG is drift-dominated, and on
  these captures a broadband RMS overstated the noise at 40 Hz by **3.5–24× in amplitude — 12–594×
  in dwell** (corrected 2026-09-13 from 20–90×, which was a hard-coded literal in a print).
- **Median in-band noise at 40 Hz after 60 s of dwell: 157 nV** (range 64–750 nV, six captures;
  corrected 2026-09-13 from 238, a median-indexing bug). Required dwell, on the noisiest capture:
  1 µV → 5.1 min; 300 nV → 56 min; 100 nV → 507 min; 30 nV → 5 628 min.
- The spread across sessions is **11.7×** and is **not attributed**: the good-contact capture has
  the *highest* 40 Hz figure, so treat it as unexplained in-band power of a scalp recording, not as
  instrument noise. No shorted-input measurement exists.
- The captures' 7.9 µV/count is the same cal-derived figure in every sidecar — consistency, not an
  independent confirmation.

> A cortical 40 Hz ASSR is plausibly within reach on this rig; a brainstem-class response (tens of
> nV) is ~two orders of magnitude out of reach. Both statements are experimental.
