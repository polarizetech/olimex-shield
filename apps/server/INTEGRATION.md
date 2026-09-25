# Adding EEG to another project

This service does two separable jobs: acquisition (core) and experimental analysis (optional
companion tools). Take either or both.

| You want | Read |
|---|---|
| To **read the EEG signal** | §1–3 below |
| The **experimental** routes (atlas, lock-in extraction, noise budget) | §4 |
| To **show a plausible EEG with no hardware attached** | `demo://synthetic`, below |

The experimental half needs no device, no `pyserial`, and no hardware — but it does need the
optional companion tools (§4). Every response from it carries `"experimental": true`.

---

## 0. Start the bridge (once, shared by everything)

```bash
python3 apps/server/serve.py 8140
```

`pip install pyserial` if you haven't — without it the acquisition half reports `supported:false` so
your app can fall back to Web Serial or a simulator.

**Only one process may hold the serial port.** That is the whole reason this is a separate service.
If another process is holding the device, close it there first — two owners cannot coexist.

**CORS is an allow-list.** A page served from `http://127.0.0.1:<port>`, `http://localhost:<port>`
or `http://[::1]:<port>` can call the bridge directly; any other origin must be listed in
`$OLIMEX_ALLOWED_ORIGINS` (comma-separated, exact). Same-origin proxies (like the workbench's
`/bridge/*`) need nothing.

The UI is `<signal-panel>` in `apps/web/signal-panel`; this process serves the backend routes it
calls.

---

## 1. Pull in the client

```html
<script src="http://localhost:8140/eeg-client.js"></script>
```

Served from the bridge so every project shares one copy and they can't drift. (Copy the file in
instead if you need the app to work with the bridge offline.)

## 2. Connect and read

```js
const eeg = new EEGClient({ base: 'http://localhost:8140' });
await eeg.connect();                 // finds a device, opens it (idempotent), starts streaming

eeg.onData(() => {
  eeg.scope(document.getElementById('scope'));   // live trace
});
// Band power: prefer POST /bands (authoritative). eeg.bands() and eeg.iaf() are kept for
// existing pages and are EXPERIMENTAL -- see the table below.
```

Reloading the page does **not** stop acquisition — the server owns the port and the client
reattaches from its last sample index.

## 3. What the read gives you

| Call | Returns |
|---|---|
| `eeg.status()` | `{supported, open, port, baud, rate, rateMeasured, rateErrorPpm, rateUncertaintyPpm, rateBasis, total, generation, parseErrors, streamGaps, maxGapUs, stream, error, recording…}` — `rate` is **declared** (250); `rateMeasured` is the host-clock measurement, `null` for the first 30 s. **Use `rateMeasured` for any lock-in** (see `RIG.md`). `parseErrors` / `streamGaps` / `maxGapUs` count what the wire lost since the port opened, from the board's `t_us` (malformed lines are dropped, never replaced) |
| `eeg.ports()` | detected serial devices |
| `eeg.connect({port,baud,channelCol})` | opens + subscribes (idempotent) |
| `eeg.recent(n)` | last *n* samples, oldest→newest |
| `eeg.bands(sec)` | **experimental, deprecated** — band powers + relative shares, same method as `POST /bands` (Hann, sum of bins, half-open bands) |
| `eeg.iaf(sec)` | **experimental, deprecated** — alpha peak 7–13 Hz, or `null` unless it is a true local peak |
| `eeg.scope(canvas, {sec,color})` | draws a live trace |
| `eeg.gaps` | count of ring-overrun gaps (you fell behind) |

Server-side "black box" recording, independent of any browser:

```js
await fetch('http://localhost:8140/record', {method:'POST',
  headers:{'Content-Type':'application/json'}, body: JSON.stringify({name:'session-01'})});
// …later
await fetch('http://localhost:8140/record/stop', {method:'POST'});
```

Files land in `apps/server/recordings/` as `sample_index,value,t_us` (older files have no `t_us`
column) with a trailing `# stopped … parse_errors=… gaps=… max_gap_us=…` line. `/record/stop`
returns the same counts as `recParseErrors`, `recGaps`, `recMaxGapUs` for the recording window.

---

## 4. The experimental routes, and where they come from

All of these live in `experimental.py` and are **experimental** (see `docs/experimental.md`):
`/predict`, `/montage`, `/simulate`, `/atlas/reference`, `/claims` come from the optional
companion **auditory-atlas** tool; `/extract*`, `/noise-budget`, `/integration-check`,
`/rate-trade`, `/detection-curve` from **signal-detection** and **injection-recovery**. The bridge
finds them through `$OLIMEX_TOOLS` (or a tools directory holding `REGISTRY.md` above this repo).
Without them those routes answer **503** with a hint, and `/health` reports `atlas: false` /
`detection: false`. Every response — 503s included — carries `"experimental": true` and a `"note"`.
`/quality`, `/bands` and `/spectrum` are this board's own and always answer.

## Hardware

Arduino + **Olimex SHIELD-EKG-EMG**, emitting CSV over serial:

```
t_us,ch0,ch1
10432,512,498
```

- **115200 baud**, ~**250 Hz**
- `channelCol` picks the column (default `1` = ch0)
- Lines starting `#` are ignored; non-numeric tokens are skipped

Any board that prints CSV lines works — this is not Olimex-specific. Note that this is **one
differential channel**: whatever montage the protocol above recommends, the device can record one
pair of it at a time.

---

## 5. Just run a session — `<signal-panel>`

`apps/web/signal-panel` (`<signal-panel>`'s Monitor tab) is the live trace, the pre-flight
plausibility check, spectrum and band powers, a server-side recorder, and a widget rack.

**Run the plausibility check before every session** — twenty seconds of pre-flight tells you whether
the channel looks like a signal or like the room. It does **not** measure impedance. Pass the
readout (`readout` or `cfg.readout`: `eeg`, `ecg`, `emg`): EEG gets the scalp amplitude floor and
an experimental alpha ratio; everything else only rails, mains share and a flat-line floor. The
**Integration check** widget (experimental, needs the companion tools) asks whether the noise will
actually average down.

**Adding your own panel**: push a `{id, title, needs, run(samples, ctx)}` object onto
`panel.widgets`. `needs` is the seconds of buffer required, so the shell refuses and says what it
is short of rather than letting your panel return nonsense from a window that is too small.

Three endpoints back it, and they are useful headless too:

| endpoint | answers |
|---|---|
| `POST /quality` | is this channel's signal plausible for the readout, and if not, which check failed (`method: "plausibility heuristic"`) |
| `POST /bands` | band powers as fractions of 1–45 Hz (a proxy — see the caveat it returns) |
| `POST /spectrum` | a coarse amplitude spectrum for drawing |

---

## Before you build a closed loop — read this

The bridge gives you a **read**. It does not validate anything about what your audio is doing.

- **Band power is a noisy proxy.** Jaw clench, blinks, and neck tension move "alpha" convincingly.
  Without artefact rejection you will build a loop that responds to your face, not your brain.
- **A closed loop is still an inference chain**: EEG → band power → "state" → audio change. Each
  arrow is an assumption.
- **One electrode montage measures one thing.** A single channel cannot tell you *where* anything
  happened, and the atlas will say so rather than let you believe otherwise.
- **A following response is not entrainment.** An FFR or ASSR at your stimulus rate is a receipt
  that the signal arrived and the pathway is intact — it is present under anaesthesia. It says the
  auditory system encoded a periodicity, not that anything downstream changed.
- **The atlas predicts; it does not measure.** Its scalp maps are a forward model from published
  anatomy. Nothing in it is evidence about your subject.
- **Baselines drift.** Compare against a same-session baseline, not an absolute threshold.
- Anything you conclude stays **[C]/[SPEC]** until it survives an artefact-rejected,
  baseline-controlled, ideally blinded measurement. The bridge doesn't change that.

Using it for **live monitoring and provenance** (watch the trace, record the raw file, timestamp
events) is solid and needs none of those caveats. Using it to *steer* audio is where the burden of
proof starts.
