# Wiring signal-panel into a project

```html
<link rel="stylesheet" href="signal-panel/signal-panel.css">
<signal-panel id="panel" bridge="bridge"></signal-panel>
```
```js
import "./signal-panel/signal-panel.js";
const p = document.getElementById("panel");
```

Serve it **by path, never copied** — a second copy of a shared component is one that drifts:

```python
PANEL = Path("apps/web/signal-panel").resolve()   # wherever this folder lives
PANEL_PUBLIC = {
    "/signal-panel/signal-panel.js":  PANEL / "signal-panel.js",
    "/signal-panel/signal-panel.css": PANEL / "signal-panel.css",
}
# ...then in translate_path(), alongside the DESIGN_PUBLIC lookup.
```

**Using the `atlas` attribute?** Add one more line to the allow-list above:

```python
"/signal-panel/atlas-panel.js": TOOLS / "auditory-atlas" / "atlas-panel.js",   # companion tool
```

and set `<signal-panel atlas bridge="bridge">`. Nothing else changes — the atlas panel is
dynamically imported the first time someone clicks the Atlas tab, reuses the same `bridge`
attribute, and reaches the design system by a dynamic import relative to its own URL
(`../design/design.js`) — the same `/design/*` mapping you already have for your own page's
`design.css`/`design.js` covers it. Skip this entirely if you don't want the Atlas tab; it costs
a host nothing until the attribute is set. The Atlas is **experimental** and the panel badges it
"beta — experimental"; see `docs/experimental.md`.

Your server still needs its `/bridge/*` proxy **including the line-by-line SSE pipe** — the
panel talks to your mount, not to the bridge directly. A JSON round trip structurally cannot
carry `/stream`: `urlopen().read()` never returns on an SSE response.

## The three things worth getting right

**1. The consent gate, if your project has one.**

```js
p.beforeConnect = async () => {
  const guide = await fetch("api/hookup").then(r => r.json());
  if (guide.error) { showError(guide.error); return false; }   // returning false ABORTS
  render(guide);
  return await userAccepted();
};
```

It is awaited, and there is no path from Connect to `/open` around it. If your project has no
gate, leave it unset.

**2. Take the signal, don't re-read it.**

```js
p.addEventListener("signal-samples", e => analyse(e.detail.values));
const last10s = p.recent(Math.round(p.info.rate * 10));
```

**3. One Record, both artefacts.** The panel's Record drives the bridge's black box. If your
project keeps its own session too, hang it off the events rather than adding a second button:

```js
p.addEventListener("signal-recording-started", startMySession);
p.addEventListener("signal-recorded", e => stopMySession(e.detail));
```

## Adding your own readout fields

```js
p.drawReadout({ "front end": gate.overall, tags: `${n} tagged` });
```

Yours are appended to the panel's `source / rate (declared) / rate (measured) / signal
(plausibility heuristic) / recording`, so there is **one** readout row rather than two competing
ones, and the panel's own redraw keeps them.

## Widgets: replacing the rack, and experimental ones

`p.widgets = [...]` remounts the rack; `p.widgets = []` hides the Widgets column (the workbench
does this when the companion analysis tools are absent). Set `experimental: true` on a widget to
give it the "beta — experimental" badge. A widget's `ctx.rate` is the measured rate when
`ctx.rateMeasured` is set and the declared one otherwise — say which in its output.

## What you must not do

- Don't infer `synthetic` from the port name — use `p.info.demo`, which comes from the
  bridge's status.
- Don't open a serial port. The bridge owns it; only one process may.
- Don't re-implement contact quality. Set `p.qualityConfig = { min_alpha_snr: 0, good_alpha_snr: 0 }`
  and every check — the one after connect and the periodic ones — sends it to the bridge's own
  check nested under `cfg` (a non-scalp host does this, because alpha is cortical and a limb or a
  plant has none). An earlier version spread the override where the bridge never looks, so it was
  silently dropped. Read `signal-quality` — and remember it is a plausibility heuristic on the
  signal, not an impedance measurement.

## Drawing your own trace: `view="controls"`

```html
<signal-panel id="panel" bridge="bridge" view="controls"></signal-panel>
```

Renders only the connection controls, banner and tier badge; no trace, readout, spectrum,
widgets or Record, and asks the bridge for none of them. Draw from the events:

```js
p.addEventListener("signal-connected",    e => start(e.detail.rate, e.detail.demo));
p.addEventListener("signal-samples",      e => push(e.detail.values, e.detail.gaps));
p.addEventListener("signal-quality",      e => showContact(e.detail));
p.addEventListener("signal-disconnected", () => stop());   // port already released when this fires
```

`e.detail.gap` is the number of samples lost immediately before this batch; don't concatenate
across one.

**Doing a lock-in at a known frequency?** Use `p.analysisRate`, not the rate from
`signal-connected`. The board's clock is ~680 ppm slow and drifts; at the declared 250 Hz a 60 Hz
line 40 dB above the floor reads "not detected" at 40 s. `analysisRate` is the bridge's live
measurement once it has 30 s, and the declared rate before that — check `p.rateInfo.measured`
(null until then) and record `p.rateInfo.basis` beside the result. `signal-rate` fires when it
updates.

**Cutting windows out of `p.recent(n)`?** The ring holds 60 s by default. Set `ring="<seconds>"`
to at least your longest window — a shorter ring does not error, it hands back fewer samples.

**Opening the port from code** (a guided run's device step): select the port, then call
`p.toggleConnect()` only when `p.info.connected` is false — it is a toggle, and pressing it while
connected disconnects. It does not throw; on failure `p.info.connected` stays false and the
bridge's reason is in `p.state.error`. Keep your own Record button and store if your project has
one — the panel's Record writes through the host's `/dataset/*` routes and is not rendered in
this view.
