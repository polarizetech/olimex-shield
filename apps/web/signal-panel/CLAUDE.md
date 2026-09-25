# CLAUDE.md — signal-panel

**One job: the live-signal panel for any page that reads the bridge.** Device picker, Connect,
Record, live trace, spectrum + band power, an extensible widget rack, source readout, the
signal-plausibility check, and three ways for the host page to get the signal back out. An
**optional** Atlas tab (`<signal-panel-atlas>`, dynamically imported from a companion tool) adds
an auditory-response planner on top.

`python3 apps/web/signal-panel/dev_check.py` (wraps `dev_check_js.mjs`, and skips it loudly
without node). Vanilla ES modules + custom elements. No build, no dependencies.

## Where it came from

It was written for an earlier internal app, and several clients of the bridge each had their own
device picker, Connect button, `EventSource` loop, ring buffer, trace canvas and readout row. This
panel is the one copy they shared. The bridge also used to serve its own scope and atlas pages;
that functionality — the more thoroughly self-tested of the two — was folded in here, and the
bridge now serves no front end. What moved in:

- **µV/count + mains** config fields, feeding the same `POST /quality` check.
- **Window / Scale / a cosmetic 1–45 Hz display filter** for the trace (never feeds a number).
- **Spectrum + band power** (`POST /spectrum`, `POST /bands`), refreshed on a ~500 ms cadence
  through the panel's existing `checkQuality()`/draw loop rather than a second timer.
- **The widget rack**: `panel.widgets` is an array of
  `{id, title, hint, needs, experimental?, controls?, run(samples, ctx)}`. `needs` is the seconds
  of buffer required — a widget that doesn't have it says so rather than returning nonsense from
  a short window. Two ship by default (integration check, lock-in at a known frequency); a host
  adds a third by pushing an object, never by editing this file. Assigning `panel.widgets`
  remounts the rack, and an empty rack hides the Widgets column.
- **The Atlas UI**, as `<signal-panel-atlas>` (`atlas-panel.js`), mounted by
  `<signal-panel atlas>` behind a "Monitor | Atlas" tab bar and dynamically imported, so a host
  that never sets `atlas` pays nothing for it.

Two regressions found by opening the merged result in a browser, both pinned as tests:
**`.ui-tabs { display: flex }` and the browser's own `[hidden] { display: none }` tie on CSS
specificity**, and the author rule wins — the tab bar showed with no `atlas` attribute until
`signal-panel [hidden] { display: none !important; }` was added. And **a shadow root was the
first attempt at giving `<signal-panel-atlas>` its own id namespace, and it was wrong**: it
isolates the design system's CLASS rules (`.ui-tabs`, `.ui-card`, `.ui-note`, `.ui-tier`) along
with the markup, since only CSS custom properties pierce a shadow boundary. `data-el` attribute
selectors scoped to `this.querySelector` already prevent the id collision, so the shadow root was
removed.

## The experimental silo

The two default widgets (integration check, lock-in) and the Atlas tab come from companion
analysis tools and are **not an established method for this hardware**. They stay usable, and
each carries a visible **"beta — experimental"** badge — the design system's own `.ui-tier` in
the `exploring` family, titled "Not an established method for this hardware; see
docs/experimental.md". The Atlas panel also gets an `exploring` rule above it. When the bridge
marks a response `experimental: true` with a `note`, the widget shows that note; nothing depends
on those fields being present.

The lock-in amplitude is printed in nV **scaled by the µV/count typed into the panel**, which is
not a calibration of this board, so it is labelled **uncalibrated**. The alpha-SNR part of the
plausibility check, when the bridge returns one, is shown as its own row with the same badge.

The workbench hides all of this when the companion tools are absent: no `atlas` attribute, and
`panel.widgets = []`.

## The seam

**The bridge owns the device and the wire. The design system owns the look. This owns
neither** — it composes them. It opens no port and holds no serial handle: every byte goes
through the *host page's own* `/bridge/*` proxy, because only the host knows its mount path and
only the bridge may hold the port.

`dev_check.py` asserts there is no `navigator.serial` anywhere in it, and no hardcoded
`localhost:8140`.

## What the host gets back — the point of the thing

A panel the host cannot read from is decoration. Three ways out, all live:

```js
el.addEventListener('signal-samples',  e => e.detail.values);   // as they arrive
el.recent(n);                                                    // last n, any time
el.addEventListener('signal-recorded', e => e.detail.id);        // a finished recording
```

plus `signal-connected`, `signal-disconnected`, `signal-quality`,
`signal-recording-started`, and `el.info` (`connected`, `recording`, `demo`, `rate`, `total`,
`quality`, `tier`, `rateMeasured`, `rateErrorPpm`).

**Rate: `el.info.rate` is DECLARED, `el.analysisRate` is for lock-in.** The bridge measures the
rate the board really delivers (`apps/server/timebase.py`, ~−680 ppm on this board, drifting);
the panel polls it and fires `signal-rate` (detail `el.rateInfo`: `declared`, `measured`,
`errorPpm`, `uncertaintyPpm`, `basis`) each time the measurement updates. `analysisRate` is the
measured value once it exists and the declared one before (~30 s). `state.rate` never changes
mid-session, because the ring and every tag are indexed by it. The readout shows
**rate (declared)** and **rate (measured)** as two rows, never one unlabelled "rate".

## Four honesty rules, held here so hosts cannot drift on them

1. **A synthetic source may not wear a MEASURED badge.** The tier comes from the bridge's own
   `status.demo`, never from the port string — a port's *name* is not what makes it synthetic.
2. **Nothing connects without the host's consent hook having run.** `beforeConnect` is awaited
   and a false return aborts. That is how the workbench's hookup guide — placements, prep, the
   **full** safety list — stays un-bypassable. The silent bypass an earlier client paid for was
   exactly a fetch that let Connect through, so the ordering is asserted against `connect()`'s
   own body rather than trusted.
3. **A stale readout is dimmed, never removed.** A field that vanishes is a field nobody notices
   is missing, and "no signal" and "no readout" look identical when one is absent.
4. **The trace states its own axes.** Volts/div and s/div are drawn. An autoscaled trace with no
   scale invites reading amplitude off a picture, and on this rig amplitude is the least safe
   thing to read that way.

Plus two inherited: drawing is `setInterval` (rAF does not run in a headless pane at all and
stops in a backgrounded tab), and the quality check is the bridge's **own** `POST /quality`, not
a local reimplementation. That check is a **signal-plausibility heuristic** (amplitude, mains
share, alpha) — not an impedance measurement — and the readout row is labelled that way.

## The ring

`recent(n)` reads from `head - filled`, never from 0. A ring read in the wrong order gives a
trace that looks perfectly plausible and is time-reversed at the wrap — the kind of bug nobody
sees. `dev_check_js.mjs` asserts it **across the wrap**, which is the only place it can fail.

## The Atlas panel

`<signal-panel-atlas>` comes from the optional auditory-atlas companion tool (found through
`$OLIMEX_TOOLS`). It talks to the bridge's backend routes through the SAME `bridge` attribute
convention as the Monitor panel — `<signal-panel>` passes its own `bridge` through unchanged when
it mounts the atlas panel, so there is one bridge address per host page, not two.

Its design helpers (`addDoc`/`marker`/`seriesColors`) are reached by a **dynamic** import
resolved relative to `atlas-panel.js`'s own URL (`../design/design.js`). A host that has not
mapped that path degrades rather than crashing: all three fall back to no-ops.

**Genuinely optional.** Pass the `atlas` attribute to get it; a host that never does pays
nothing (`atlas-panel.js` is never fetched). A host that DOES want it must also serve
`atlas-panel.js` next to `signal-panel.js`/`signal-panel.css` — see `INTEGRATION.md`.

## `view="controls"` — for a host that draws its own view

Some hosts exist *because* of a domain-specific trace the panel's plain one cannot draw (a
deviation overlay, an ECG waterfall with beat marks), or draw no trace at all. Those set
`view="controls"`: the panel renders the device picker, µV/count, mains, Connect, Rescan, the tier
badge and the error banner — and **not** its trace, readout, spectrum, widgets or Record button.
It also never asks the bridge for spectrum, bands or widget results, so a hidden panel costs no
server work. The periodic quality check still runs; the host reads it from `signal-quality` and
draws from `signal-samples`.

## Bugs found wiring earlier clients to it — all pinned

- **The `cfg` override never reached the check.** `checkQuality(cfg)` spread the override at the
  top level of the request; the bridge reads `body["cfg"]`. A non-scalp host's disabled alpha-SNR
  gate would have been silently dropped. It is sent nested now, and `panel.qualityConfig` applies
  it to the periodic check too.
- **The rate key was wrong twice.** The panel read `rate_hz` from `/open` and `/status` and sent
  `rate_hz` to `/quality`; the bridge's key is `rate` in both directions. Every connection fell
  back to 250 Hz — correct on this rig by coincidence only.
- **A down bridge said nothing.** A host proxy answers with a JSON `{error, hint}`, so nothing
  threw and the picker quietly offered only the demo port. It is reported in the banner now.
- **Stream gaps were concatenated.** A tab that fell behind the bridge's ring silently compressed
  time. Jumps in the SSE `from` offset are counted now, on `info.gaps` and on each
  `signal-samples` event.
- **A double click could stack a second gate** while the first was still open. Guarded.
- **An already-open port replayed its whole ring as live.** The stream opened with no `from`,
  which the bridge reads as 0; `/open` is idempotent, so a port another tab had left open replayed
  up to 60 s of old samples as though new. The stream now starts 2 s back from the bridge's total.
- **A disconnect inside the 4 s after connect could still produce a quality verdict** about a
  closed port. Re-checked after the wait.
- **`ring="320"`** — the ring was fixed at 60 s, and a ring shorter than a capture window does not
  error, it returns fewer samples. A host that cuts long windows sets the attribute.
- **`panel.port`** — the selected port, for a UX decision such as skipping a hookup guide for the
  bridge's own generator. Never for a tier; that is still `info.demo`.
- **The readout was never drawn.** `drawReadout()` existed but nothing called it; the frame loop
  now does, and a host's extra fields passed to `drawReadout(extra)` survive the redraw.

Each client was verified in a browser against the bridge's synthetic port, **none with a person
on the electrodes**.

## Not built yet

**Playback in the same view.** One panel showing a trace with its timeline and tags from any of
three sources — the live bridge, a saved session, or an external dataset. The workbench's
Sessions tab (`playback.js`) does the saved-session part separately today. **Stimulus-to-effect
alignment** is the same tag track fed by code rather than a keypress; the hard part is the clock
(browser audio time vs. the sample index). Trade-off to decide then: this makes the panel a
player as well as a monitor; a separate player needs its own copy of the trace and timeline.

## What it does not do

No verdicts beyond what the bridge itself returns, no local reimplementation of a band power or
a spectrum (`dev_check.py` asserts no `goertzel`/`fft` anywhere in this file — those numbers come
from the bridge). The browser draws; the server computes. It has never been seen on a phone.
