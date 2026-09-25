/* signal-panel.js -- ONE live-signal panel, for every page that reads the shared bridge.
 *
 * <signal-panel bridge="bridge" readout="ecg"></signal-panel>
 * <signal-panel bridge="bridge" readout="eeg" atlas></signal-panel>   -- adds an Atlas tab
 *
 * *** WHY THIS EXISTS. ***
 *
 * Several earlier clients of the bridge each wrote their own device picker, Connect button,
 * EventSource loop, ring buffer, trace canvas and readout row. This panel is the one copy
 * they share, so a fix to any of those reaches every host at once.
 *
 * *** WHAT CAME FROM THE BRIDGE'S FORMER SCOPE PAGE (2026-09-14). ***
 *
 * The bridge used to serve a second, independently-written front end (a scope page and an
 * atlas page) with a spectrum/band-power view and an extensible widget rack this panel did not
 * have. Per the operator's direction, that functionality -- being the more thoroughly
 * self-tested of the two -- is now folded in here as the winning implementation, and the bridge
 * no longer serves any front end at all. What moved in:
 *   - a µV/count + mains config (feeds the quality gate, as the scope page did)
 *   - window / scale / a cosmetic 1-45 Hz display filter for the trace
 *   - the spectrum + band-power view (`/spectrum`, `/bands`)
 *   - the WIDGET CONTRACT: `{id, title, hint, needs, controls?, run(samples, root)}` pushed
 *     onto `panel.widgets`. `needs` is the seconds of buffer required; the shell greys a
 *     widget out and says what it is short of rather than letting it return nonsense from a
 *     window too small. Two widgets ship by default (integration check, lock-in at a known
 *     frequency); a host adds a third by pushing a fourth object, not by touching this file.
 *   - the Atlas UI (`signal-panel-atlas`, `atlas-panel.js`), as an OPTIONAL tab: pass the
 *     `atlas` attribute and a "Monitor | Atlas" tab bar appears. Atlas is dynamically
 *     imported on first use, so a host that never sets `atlas` pays nothing for it.
 * The scope page's stated rule travels with its code: every NUMBER on the page comes from the
 * server (`/quality`, `/bands`, `/spectrum`, `/integration-check`, `/extract`) because those
 * are what the bridge's stdlib Python `apps/server/dev_check.py` tests. Reimplementing a band
 * power here to save a round trip is how two answers to the same question start disagreeing.
 * The one exception is the display filter, which is cosmetic and never feeds a readout.
 *
 * The seam this respects: **the bridge owns the device and the wire, the design system owns
 * the look, and this owns neither.** It is a panel that composes them. It opens no port -- every
 * byte goes through the host page's own `/bridge/*` proxy, because only the host knows its
 * mount path and only the bridge may hold the serial port.
 *
 * *** WHAT THE HOST GETS BACK, WHICH IS THE POINT. ***
 *
 * A panel is useless if the host cannot use the signal. Three ways out, all of them live:
 *
 *     el.addEventListener('signal-samples', e => e.detail.values)   // as they arrive
 *     el.recent(n)                                                  // last n, any time
 *     el.addEventListener('signal-recorded', e => e.detail.id)      // a finished recording
 *
 * so a host can drive a live analysis, a sonifier, or a stored-session pipeline without
 * knowing anything about SSE, ring buffers or the bridge's route names.
 *
 * *** THE HONESTY RULES IT CARRIES, so that no two hosts can drift on them. ***
 *
 * 1. A SYNTHETIC SOURCE MAY NOT WEAR A MEASURED BADGE. The tier is read from the bridge's own
 *    `status.demo`, never from the port string -- a port's NAME is not what makes it
 *    synthetic.
 * 2. NOTHING CONNECTS WITHOUT THE HOST'S CONSENT HOOK HAVING RUN. `beforeConnect` is awaited
 *    and a false return aborts. That is how the workbench's hookup guide (placements,
 *    prep, the FULL safety list) stays un-bypassable: the silent-bypass bug an earlier
 *    client paid for was exactly a fetch that let Connect through.
 * 3. A STALE READOUT IS DIMMED, NEVER REMOVED. A field that vanishes is a field nobody
 *    notices is missing, and "no signal" and "no readout" look identical when one is absent.
 * 4. THE TRACE IS NOT AN OSCILLOSCOPE UNTIL IT SAYS WHAT ITS AXES ARE. Autoscaled traces with
 *    no scale invite reading amplitude off a picture. Volts/div and time/div are drawn.
 *
 * Vanilla ES module, no build, no dependencies. Colours and type come from the design system;
 * `dev_check.py` fails on a literal here.
 */

const RING_S = 60;
const DRAW_MS = 100;
const ANALYSIS_EVERY_N_TICKS = 5;      // ~500 ms, the same cadence the scope page used
const RATE_EVERY_N_TICKS = 50;         // ~5 s: the bridge's rate estimate moves slowly

/* Tag labels the operator has used this session, in order, so keys 1-9 stay stable. */
const MAX_QUICK = 9;

/* setInterval, not rAF. rAF does not run in a headless verification pane at all and stops in
 * a backgrounded tab, and the normal case here is an operator looking away from a running
 * session. Several earlier apps each reached this independently before this file existed. */
const css = (v, el) => getComputedStyle(el || document.body).getPropertyValue(v).trim();

/* Cosmetic only -- a one-pole high-pass at 1 Hz plus a one-pole low-pass at 45 Hz, ported from
 * the scope page. It exists so the eye can see the EEG under the drift; it NEVER feeds a number. */
function displayFilter(x, fs) {
  const hp = Math.exp(-2 * Math.PI * 1 / fs), lp = Math.exp(-2 * Math.PI * 45 / fs);
  const out = new Float32Array(x.length);
  let px = 0, py = 0, ly = 0;
  for (let i = 0; i < x.length; i++) {
    const y = hp * (py + x[i] - px); px = x[i]; py = y;
    ly = (1 - lp) * y + lp * ly; out[i] = ly;
  }
  return out;
}

/* *** THE EXPERIMENTAL SILO. ***
 * The two default widgets and the Atlas tab come from companion analysis tools that are NOT an
 * established method for this hardware. They stay usable, and they are visibly badged -- a
 * lock-in amplitude printed without a badge reads as a measurement. The bridge may also mark a
 * response `experimental: true` with a `note`; that note is shown when present, and nothing
 * here depends on it being there. */
const EXPERIMENTAL_TITLE =
  'Not an established method for this hardware; see docs/experimental.md';
export const betaBadge = () =>
  `<span class="ui-tier sp-beta" data-family="exploring" title="${EXPERIMENTAL_TITLE}">`
  + 'beta — experimental</span>';
const escText = (v) => String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;');
/** The bridge's own caveat for an experimental response, if it sent one. */
const serverNote = (r) => (r && r.note
  ? `<p class="ui-note sp-w-note" style="font-size:var(--text-xs);margin:8px 0 0">${escText(r.note)}</p>`
  : '');

/* The default widget rack, ported from the scope page (same routes, same hints). A host
 * pushes more onto `el.widgets` before or after `connectedCallback` runs. */
function defaultWidgets() {
  return [
    {
      id: 'integration', title: 'Integration check', needs: 90, experimental: true,
      hint: "Does this channel's noise actually average down? Measured on this rig, 4 of 9 "
        + 'baselines FAIL -- and on those, recording for longer buys nothing.',
      async run(samples, ctx) {
        const r = await ctx.post('/integration-check', { samples, rate: ctx.rate, ref_hz: 40 });
        return `<div class="ui-note" style="font-weight:600">${r.integrates ? 'integrates' : 'drift-limited'}</div>
          <p class="ui-mono" style="font-size:var(--text-xs);margin:8px 0 0">ratio ${r.ratio.toFixed(2)} · ${escText(r.reading)}</p>${serverNote(r)}`;
      },
    },
    {
      id: 'lockin', title: 'Lock-in at a known frequency', needs: 20, experimental: true,
      hint: 'Only meaningful if you are PLAYING this exact frequency. Otherwise it measures the '
        + 'noise there. The amplitude is scaled by the µV/count you entered, which is NOT a '
        + 'calibration of this board -- read it as uncalibrated.',
      controls: '<label class="ui-field" style="margin-bottom:8px">Hz <input class="sp-w-hz" value="40" size="6"></label>',
      async run(samples, ctx) {
        const hz = +ctx.root.querySelector('.sp-w-hz').value || 40;
        const r = await ctx.post('/extract', { samples, rate: ctx.rate, ref_hz: hz, sync: 'nominal_frequency' });
        const p = r.presence[0], lk = r.bank[0];
        // The rate row names WHICH rate the lock-in ran at: the bridge's measured rate once it
        // exists, the declared rate until then. Never an unlabelled "rate".
        return `<dl class="ui-readout" style="margin:0">
          <dt>amplitude (uncalibrated)</dt><dd>${(lk.amplitude * (ctx.uvpc || 1) * 1000).toFixed(0)} nV × (your µV/count, not calibrated)</dd>
          <dt>${ctx.rateMeasured ? 'rate (measured)' : 'rate (declared)'}</dt><dd>${ctx.rate.toFixed(3)} Hz ${ctx.rateMeasured ? 'measured' : 'DECLARED — not yet measured'}</dd>
          <dt>p (F-test)</dt><dd>${p.f_test.p.toExponential(2)}</dd>
          <dt>SNR</dt><dd>${p.f_test.snr_db.toFixed(1)} dB</dd>
          <dt>tier</dt><dd>${escText(lk.tier)}</dd></dl>
          <p class="ui-mono" style="font-size:var(--text-xs);margin:8px 0 0;color:var(--muted-foreground)">${escText(p.statement)}</p>${serverNote(r)}`;
      },
    },
  ];
}

/** The alpha-SNR part of the bridge's plausibility check, whatever shape it arrives in: a bare
 *  number (`alpha_snr`), or a sub-result object carrying `experimental`. Null if absent. */
export function alphaSnrOf(q) {
  if (!q) return null;
  const a = q.alpha_snr;
  if (typeof a === 'number' && Number.isFinite(a)) return a;
  for (const o of [a, q.alpha, q.alpha_check]) {
    if (o && typeof o === 'object') {
      for (const k of ['value', 'snr', 'alpha_snr', 'ratio']) {
        if (typeof o[k] === 'number' && Number.isFinite(o[k])) return o[k];
      }
    }
  }
  return null;
}

export class SignalPanel extends HTMLElement {
  constructor() {
    super();
    this.state = {
      connected: false, recording: false, demo: null, rate: 0,
      ring: new Float32Array(250 * RING_S), head: 0, filled: 0, total: 0,
      lastSampleAt: 0, quality: null, spectrum: null, bands: null, recordingId: null,
      error: null, tags: [], quick: [], stamp: null, recordStart: 0,
      window: 5, scale: 0, filter: true, gaps: 0,
      rateMeasured: null, rateErrorPpm: null, rateUncertaintyPpm: null, rateBasis: null,
    };
    /** Awaited before any port is opened. Return false to abort. The host's gate. */
    this.beforeConnect = null;
    /** The widget rack. Push {id, title, hint, needs, controls?, run(samples, ctx)} onto this
     *  before connectedCallback fires (or any time after -- mountWidgets() is idempotent). */
    this.widgets = defaultWidgets();
    this._readoutExtra = null;
    /** A host-set override merged into every quality check (initial AND periodic), nested
     *  under the bridge's own `cfg` key. Non-scalp hosts (a limb lead, a plant electrode)
     *  need this to disable the alpha-SNR gate -- alpha is cortical, and a limb or a tree has
     *  none. Set it any time; it takes effect on the next check. */
    this.qualityConfig = null;
    this._es = null;
    this._timer = null;
    this._tick = 0;
    this._widgetBusy = false;
    this._atlasEl = null;
  }

  /** Replacing the rack remounts it, so a host that sets `widgets = []` (the workbench does,
   *  when the companion analysis tools are absent) hides the badged widgets rather than leaving
   *  inert ones on the page. */
  get widgets() { return this._widgets; }
  set widgets(v) {
    this._widgets = Array.isArray(v) ? v : [];
    if (this.$) this._mountWidgets();
  }

  get bridge() { return this.getAttribute('bridge') || 'bridge'; }
  get base() { return new URL(this.bridge.replace(/\/$/, '') + '/', document.baseURI); }
  _url(p) { return new URL(p.replace(/^\//, ''), this.base).toString(); }
  /** The host's dataset mount. Sibling of the page, not of the bridge proxy. */
  _url2(p) { return new URL(p.replace(/^\//, ''), document.baseURI).toString(); }

  async _post(path, body) {
    const r = await fetch(this._url(path), {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }

  connectedCallback() {
    this.innerHTML = TEMPLATE;
    this.$ = (c) => this.querySelector('[data-el="' + c + '"]');
    this.$('connect').onclick = () => this.toggleConnect();
    this.$('record').onclick = () => this.toggleRecord();
    this.$('rescan').onclick = () => this.listPorts();
    this.$('tagbtn').onclick = () => this.tag();
    this.$('taglabel').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === 'Return') { e.preventDefault(); this.tag(); }
    });
    this.$('uvpc').value = this.getAttribute('uvpc') || '7.9';
    this.$('mains').value = this.getAttribute('mains') || '60';
    for (const id of ['win', 'scale', 'filt']) {
      this.$(id).addEventListener('change', () => this._syncTraceControls());
    }
    this._syncTraceControls();
    // Keys 1-9 fire the quick tags. A session where tagging is slow is a session where the
    // tag lands late, and the lag between the thing and the keypress is already the largest
    // unmeasured error in any analysis of these marks.
    this._keys = (e) => {
      if (!this.state.recording) return;
      const t = e.target.tagName;
      if (t === 'INPUT' || t === 'SELECT' || t === 'TEXTAREA') return;
      const i = '123456789'.indexOf(e.key);
      if (i >= 0 && this.state.quick[i]) { e.preventDefault(); this.tag(this.state.quick[i]); }
    };
    document.addEventListener('keydown', this._keys);
    if (this.controlsOnly) {
      for (const id of ['record', 'scope', 'readout', 'analysis']) this.$(id).hidden = true;
    }
    this._mountWidgets();
    this._setupTabs();
    this.listPorts();
    this._timer = setInterval(() => this._frame(), DRAW_MS);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    if (this._keys) document.removeEventListener('keydown', this._keys);
    if (this._es) this._es.close();
  }

  _frame() {
    if (!this.controlsOnly) { this.draw(); this.drawTimeline(); this.drawReadout(); }
    this._tick++;
    if (this._tick % ANALYSIS_EVERY_N_TICKS === 0) this._refreshAnalysis();
    if (this._tick % RATE_EVERY_N_TICKS === 0) this._refreshRate();
  }

  /** The bridge measures the rate the board actually delivers (apps/server/timebase.py).
   *  It needs ~30 s, so it is polled rather than read once at connect. `state.rate` is NOT
   *  changed by it: the ring, the trace and the tag clock keep the declared rate, because a rate
   *  that moved mid-session would move every tag. Only lock-in work uses `analysisRate`. */
  async _refreshRate() {
    const s = this.state;
    if (!s.connected) return;
    try {
      const st = await fetch(this._url('status')).then((x) => x.json());
      const had = s.rateMeasured;
      s.rateMeasured = st.rateMeasured ?? null;
      s.rateErrorPpm = st.rateErrorPpm ?? null;
      s.rateUncertaintyPpm = st.rateUncertaintyPpm ?? null;
      s.rateBasis = st.rateBasis ?? null;
      if (s.rateMeasured !== had) this._emit('signal-rate', this.rateInfo);
    } catch { /* the stream is the thing that matters; a missed status poll is not */ }
  }

  get rateInfo() {
    const s = this.state;
    return { declared: s.rate, measured: s.rateMeasured, errorPpm: s.rateErrorPpm,
             uncertaintyPpm: s.rateUncertaintyPpm, basis: s.rateBasis };
  }

  /** The rate to use for LOCK-IN: measured once the bridge has it, declared until then. At
   *  -644 ppm a lock-in at the declared rate nulls a 40 dB line within 40 s (RIG.md). */
  get analysisRate() { return this.state.rateMeasured || this.state.rate; }

  _syncTraceControls() {
    const s = this.state;
    s.window = +this.$('win').value || 5;
    s.scale = +this.$('scale').value || 0;
    s.filter = this.$('filt').checked;
  }

  /* ------------------------------------------------------------------ the host's handles */
  /** The last `n` samples, oldest first. The ring is read from head-filled, never from 0 --
   *  reading it in the wrong order gives a trace that looks plausible and is time-reversed
   *  at the wrap, which is the kind of bug nobody sees. */
  recent(n) {
    const s = this.state, len = Math.min(n ?? s.filled, s.filled);
    const out = new Float32Array(len);
    const start = (s.head - len + s.ring.length) % s.ring.length;
    for (let i = 0; i < len; i++) out[i] = s.ring[(start + i) % s.ring.length];
    return out;
  }

  get info() {
    const s = this.state;
    // `rate` is the DECLARED rate. `rateMeasured` is null until the bridge has measured it.
    return { connected: s.connected, recording: s.recording, demo: s.demo, rate: s.rate,
             rateMeasured: s.rateMeasured, rateErrorPpm: s.rateErrorPpm,
             total: s.total, quality: s.quality, gaps: s.gaps,
             tier: s.demo === null ? null : (s.demo ? 'MODELLED' : 'MEASURED') };
  }

  /** The selected port. A host MAY use this for a UX decision (e.g. skip a hookup guide for
   *  the bridge's own generator) -- never for a tier; that comes from `info.demo`. */
  get port() { return this.$ ? this.$('port').value : ''; }

  /** `view="controls"`: connection, config, banner and the quality gate only. For a host that
   *  draws its OWN domain view (a deviation overlay, a beat detector) from `signal-samples` --
   *  the trace, readout, spectrum, widgets and the Record button are not rendered, and the
   *  spectrum/bands/widget requests are never made, so a hidden panel costs no server work. */
  get controlsOnly() { return this.getAttribute('view') === 'controls'; }

  /** `ring="320"`: how many seconds `recent(n)` can reach back. 60 by default. A host that cuts
   *  windows longer than that out of the ring MUST raise it -- a ring shorter than the window
   *  does not error, it silently returns fewer samples than were recorded. A host that
   *  captures 60 s blocks might size the ring at 320 s for headroom. */
  get ringSeconds() {
    const v = Number(this.getAttribute('ring'));
    return Number.isFinite(v) && v >= 1 ? v : RING_S;
  }

  _emit(name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true }));
  }

  /* ------------------------------------------------------------------------ the plumbing */
  async listPorts() {
    const sel = this.$('port');
    try {
      const r = await fetch(this._url('ports')).then((x) => x.json());
      // A host proxy answers a DOWN bridge with a JSON body ({error, hint}), so nothing
      // throws -- without this the picker just showed the demo option and said nothing.
      if (r.error) this.fail(r.error + (r.hint ? ` — start it with: ${r.hint}` : ''));
      const list = (r.ports || []).map((p) => (typeof p === 'string' ? p : p.device));
      sel.innerHTML = list.map((p) => `<option value="${p}">${p}</option>`).join('')
        + `<option value="demo://synthetic">demo://synthetic</option>`;
      if (!list.length) sel.selectedIndex = 0;
    } catch (e) {
      sel.innerHTML = `<option value="demo://synthetic">demo://synthetic</option>`;
      this.fail(`could not list ports: ${e}. Is the bridge running?`);
    }
  }

  async toggleConnect() {
    if (this.state.connected) return this.disconnect();
    // A second click while the host's gate is open, or while /open is in flight, must not
    // stack a second gate or a second open. An earlier client carried this guard in its own
    // hand-rolled connect(); it belongs here, where every consumer gets it.
    if (this._connecting) return;
    this._connecting = true;
    try { await this._connect(); } finally { this._connecting = false; }
  }

  async _connect() {
    this.fail('');
    // RULE 2. The host's gate runs FIRST and is awaited. A false return aborts, and there is
    // no path past this line to /open.
    if (typeof this.beforeConnect === 'function') {
      let go = false;
      try { go = await this.beforeConnect(this); } catch (e) { return this.fail(String(e)); }
      if (!go) return;
    }
    const port = this.$('port').value;
    let r;
    try {
      r = await fetch(this._url('open'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port, baud: 115200 }),
      }).then((x) => x.json());
    } catch (e) { return this.fail(`bridge unreachable: ${e}`); }
    // The bridge answers 404 with a JSON BODY, so a wrong route makes nothing throw and the
    // UI simply never connects. apps/server/RIG.md records that trap; this checks.
    if (r.error) return this.fail(r.error + (r.hint ? ` — ${r.hint}` : ''));

    const st = await fetch(this._url('status')).then((x) => x.json()).catch(() => ({}));
    const s = this.state;
    s.connected = true;
    // REGRESSION: this read `rate_hz`, which the bridge has never sent -- its key is `rate` --
    // so every connection silently fell back to 250. Right on this rig by coincidence only.
    s.rate = Number(r.rate || st.rate) || 250;
    s.gaps = 0;
    // A new connection is a new clock: never carry a previous port's measured rate across.
    s.rateMeasured = st.rateMeasured ?? null; s.rateErrorPpm = st.rateErrorPpm ?? null;
    s.rateUncertaintyPpm = st.rateUncertaintyPpm ?? null; s.rateBasis = st.rateBasis ?? null;
    s.demo = !!st.demo;                       // RULE 1: from status, never from the port name
    s.ring = new Float32Array(Math.max(256, Math.round(this.ringSeconds * s.rate)));
    s.head = 0; s.filled = 0; s.total = 0;
    this.$('connect').textContent = 'Disconnect';
    this.$('record').disabled = false;
    // REGRESSION: the stream was opened with no `from`, which the bridge reads as 0. `/open` is
    // idempotent -- if the port was ALREADY open (another tab, a reload) it keeps its ring, so
    // from=0 replayed up to 60 s of old samples in one batch as though they had just arrived:
    // stale beats in a heart rate, stale excursions on a trace. Start 2 s back instead, the
    // backfill an earlier ECG client had already chosen for itself. A fresh open has total ~0,
    // so nothing changes there.
    this.openStream(Math.max(0, (Number(st.total) || 0) - Math.round(2 * s.rate)));
    this._emit('signal-connected', { ...this.info, port });
    this.checkQuality();
  }

  async disconnect() {
    if (this._es) { this._es.close(); this._es = null; }
    await fetch(this._url('close'), { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' }).catch(() => {});
    const s = this.state;
    s.connected = false; s.demo = null;
    this.$('connect').textContent = 'Connect';
    this.$('record').disabled = true;
    this._emit('signal-disconnected', {});
  }

  openStream(from = 0) {
    if (this._es) this._es.close();
    this._es = new EventSource(this._url('stream') + `?from=${from}`);
    // A jump in `from` is a GAP -- the bridge's ring overran while this tab was away -- and
    // concatenating across one compresses time and puts every frequency out. Counted and
    // reported rather than hidden. Ported from an earlier client, which had it and this lacked.
    let expect = null;
    this._es.onmessage = (ev) => {
      let d; try { d = JSON.parse(ev.data); } catch { return; }
      const vals = d.samples || d.values || [];
      if (!vals.length) return;
      const s = this.state;
      let gap = 0;
      if (expect !== null && typeof d.from === 'number' && d.from > expect) gap = d.from - expect;
      if (typeof d.from === 'number') expect = d.from + vals.length;
      s.gaps += gap;
      s.lastSampleAt = performance.now();
      const flat = vals.map((v) => (Array.isArray(v) ? v[0]
        : (v && typeof v === 'object' ? v.ch0 : v)));
      for (const x of flat) {
        s.ring[s.head] = x;
        s.head = (s.head + 1) % s.ring.length;
        if (s.filled < s.ring.length) s.filled++;
        s.total++;
      }
      this._emit('signal-samples', { values: flat, total: s.total, rate: s.rate, gap, gaps: s.gaps });
      // Stored from the instant recording starts, not from when the store answers. The tag
      // clock is zeroed at that same instant (`recordStart`), so sample 0 and t_s = 0 agree.
      if (s.recording) this._store(flat);
    };
    this._es.onerror = () =>
      this.fail('the sample stream dropped; the bridge may have closed the port');
  }

  /** The bridge's OWN quality gate (POST /quality), never a local reimplementation. Called
   *  once, ~4 s after connect, AND on the periodic analysis cadence once enough buffer exists
   *  -- so the readout keeps tracking contact through a session, not just at its start.
   *  `cfg` (or `this.qualityConfig` if unset) is sent NESTED under the bridge's own `cfg`
   *  key -- REGRESSION: an earlier version spread it at the top level, which the bridge
   *  silently ignored (`body.get("cfg")` saw nothing), so a host's alpha-SNR override never
   *  reached the gate. `{immediate: true}` skips the 4 s delay without implying a cfg. */
  async checkQuality(cfg, { immediate = false } = {}) {
    const s = this.state;
    if (!s.connected) return null;
    if (!immediate) await new Promise((r) => setTimeout(r, 4000));
    // Re-checked after the wait: a disconnect inside those 4 s must not produce a verdict about a
    // port that is already closed. Seen in an earlier client's network log.
    if (!s.connected) return null;
    const samples = Array.from(this.recent(Math.round(s.rate * 4)));
    if (samples.length < 64) return null;
    const c = cfg !== undefined ? cfg : this.qualityConfig;
    try {
      // `rate`, not `rate_hz`: the bridge reads body["rate"] and defaults to 250 without it.
      s.quality = await this._post('quality', {
        samples, rate: s.rate, uv_per_count: +this.$('uvpc').value || 1,
        mains_hz: +this.$('mains').value || 60, ...(c ? { cfg: c } : {}),
      });
      this._emit('signal-quality', s.quality);
    } catch { /* a missing quality gate is not a reason to stop a session */ }
    return s.quality;
  }

  /* ------------------------------------------------------------------------ spectrum/bands */
  async _refreshAnalysis() {
    const s = this.state;
    if (!s.connected) return;
    await this.checkQuality(this.qualityConfig, { immediate: true });
    if (this.controlsOnly) return;             // the host draws its own view; ask for nothing else
    const long =Array.from(this.recent(Math.min(s.filled, Math.round(s.rate * 20))));
    if (long.length < s.rate * 2) return;
    try {
      s.spectrum = await this._post('spectrum', { samples: long, rate: s.rate });
      this.drawSpectrum();
    } catch { /* spectrum is decoration; never let it kill the loop */ }
    try {
      s.bands = await this._post('bands', { samples: long, rate: s.rate });
      this.drawBands();
    } catch { /* same */ }
    this._runWidgets();
  }

  drawSpectrum() {
    const c = this.$('spec'), s = this.state.spectrum;
    if (!c || !c.clientWidth || !s) return;
    const r = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * r)) { c.width = Math.round(w * r); c.height = Math.round(h * r); }
    const g = c.getContext('2d');
    g.setTransform(r, 0, 0, r, 0, 0);
    g.clearRect(0, 0, w, h);
    const freqs = s.freqs || [], amps = s.amps || [];
    if (!freqs.length) return;
    let max = 0; for (const a of amps) max = Math.max(max, a);
    if (!max) return;
    g.fillStyle = css('--predicted', this);
    const bw = w / freqs.length;
    for (let i = 0; i < freqs.length; i++) {
      const bh = (amps[i] / max) * (h - 18);
      g.fillRect(i * bw, h - 14 - bh, Math.max(1, bw - 1), bh);
    }
    g.fillStyle = css('--faint-foreground', this) || css('--foreground', this);
    g.font = '10px ui-monospace, monospace';
    for (const f of [10, 20, 30, 40]) {
      const i = freqs.findIndex((v) => v >= f);
      if (i > 0) g.fillText(String(f), i * bw - 5, h - 3);
    }
  }

  drawBands() {
    const b = this.state.bands;
    if (!b) return;
    this.$('bands').innerHTML = ['delta', 'theta', 'alpha', 'beta', 'gamma'].map((k) => `
      <div class="sp-bandrow"><span>${k}</span>
        <span class="sp-meter"><i style="width:${((b[k] || 0) * 100).toFixed(1)}%"></i></span>
        <span>${((b[k] || 0) * 100).toFixed(1)}%</span></div>`).join('');
  }

  /* -------------------------------------------------------------------------- widget rack */
  _mountWidgets() {
    const host = this.$('widgets');
    if (!host) return;
    // No widgets, no Widgets column: an empty heading reads as "broken", not "not installed".
    const col = this.$('widgetcol');
    if (col) col.hidden = !this.widgets.length;
    host.innerHTML = this.widgets.map((w) => `
      <div class="sp-widget" data-wid="${w.id}">
        <h3>${w.title}${w.experimental ? ' ' + betaBadge() : ''}</h3>
        <p class="ui-note" style="font-size:var(--text-xs);margin:0 0 8px">${w.hint}</p>
        ${w.controls || ''}
        <div class="sp-w-out ui-mono" style="font-size:var(--text-xs)">needs ${w.needs} s of buffer</div>
      </div>`).join('');
  }

  async _runWidgets() {
    if (this._widgetBusy) return;               // one pass at a time; these are O(n) server-side
    this._widgetBusy = true;
    // try/FINALLY, not try/catch: anything escaping this loop leaving the guard stuck true
    // would freeze every widget permanently while the trace kept updating -- the scope page's
    // bug this rack inherits the fix for. A guard flag that can leak is worse than no guard.
    try {
      const s = this.state;
      for (const w of this.widgets) {
        const root = this.querySelector(`.sp-widget[data-wid="${w.id}"]`);
        if (!root) continue;
        const out = root.querySelector('.sp-w-out');
        if (!out) continue;
        const have = s.rate ? s.filled / s.rate : 0;
        if (have < w.needs) { out.textContent = `needs ${w.needs} s of buffer — have ${have.toFixed(0)} s`; continue; }
        // Widgets do lock-in work, so they get the measured rate when it exists -- and are told
        // which they got, so a result can say so.
        const ctx = {
          root, rate: this.analysisRate, rateMeasured: s.rateMeasured,
          uvpc: +this.$('uvpc').value || 1,
          post: (path, body) => this._post(path, body),
        };
        try { out.innerHTML = await w.run(Array.from(this.recent(Math.round(w.needs * s.rate))), ctx); }
        catch (e) { out.textContent = String((e && e.message) || e); }
      }
    } finally { this._widgetBusy = false; }
  }

  /* --------------------------------------------------------------------------- recording */
  async toggleRecord() {
    const s = this.state;
    if (s.recording) return this.stopRecording();
    try {
      // *** EVERY BLACK BOX GETS ITS OWN NAME. ***
      // An empty body made the bridge write `capture.csv` every time, so each recording
      // silently overwrote the previous session's black box. Found 2026-09-15 on the real board.
      const name = 'rec-' + new Date().toISOString().replace(/[-:]/g, '').replace(/\..*/, '')
        + '-' + Math.random().toString(36).slice(2, 6);
      const r = await fetch(this._url('record'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      }).then((x) => x.json());
      if (r.error) return this.fail(r.error);
      this._pending = []; this._appendChain = Promise.resolve(); this._noStore = false;
      s.recording = true;
      s.recordingId = r.recPath ? String(r.recPath).split(/[\\/]/).pop() : (r.id || r.recording_id || null);
      s.tags = []; s.quick = []; s.stamp = null;
      // *** THE TAG CLOCK IS ZEROED HERE, AND GETTING THIS WRONG IS SILENT. ***
      // `s.total` counts from CONNECT; the dataset's sample index counts from RECORD. A tag
      // timed against the first would sit at 77 s in a 23 s session -- found by reading a
      // recorded sidecar, not by any assertion, and it would have misaligned every tag
      // against its own samples without anything looking wrong.
      s.recordStart = s.total;
      this.renderQuick();
      // TWO ARTEFACTS, ONE ACTION. The bridge writes its black box (it holds the port, so it
      // survives this tab closing); the dataset writes the session with its tag track. A
      // dataset mount that is absent is not an error -- a host may not want a store.
      const meta = { project: this.getAttribute('project') || 'unknown',
                     readout: this.getAttribute('readout') || 'unknown',
                     source: s.demo ? 'synthetic' : 'electrode',
                     rate_hz: s.rate, black_box: s.recordingId,
                     electrodes_on_at: Math.floor(Date.now() / 1000),
                     ...(this.sessionMeta ? this.sessionMeta() : {}) };
      const d = await fetch(this._url2('dataset/start'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(meta),
      }).then((x) => x.json()).catch(() => null);
      if (d && d.stamp) { s.stamp = d.stamp; this._flush(); }
      else {
        // No store mounted (or it refused): do not buffer a session nobody will receive.
        this._noStore = true; this._pending = [];
        if (d && d.error) this.fail(d.error);
      }
      this.$('tagbar').hidden = false;
      this.$('record').textContent = 'Stop';
      this._emit('signal-recording-started', { id: s.recordingId, stamp: s.stamp });
    } catch (e) { this.fail(`could not start recording: ${e}`); }
  }

  async stopRecording() {
    const s = this.state;
    try {
      // Stop buffering FIRST, then send what is buffered, then close the session. A stop that
      // did not flush dropped up to one batch (~1 s) off the end of every recording: measured
      // on the real board as 1859 stored against 2020 in the black box.
      s.recording = false;
      await this._flush();
      const r = await fetch(this._url('record/stop'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      }).then((x) => x.json());
      this.$('tagbar').hidden = true;
      this.$('record').textContent = 'Record';
      let stopped = null;
      if (s.stamp) {
        stopped = await fetch(this._url2('dataset/stop'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stamp: s.stamp }),
        }).then((x) => x.json()).catch(() => null);
      }
      this._emit('signal-recorded',
                 { id: s.recordingId, stamp: s.stamp, tags: s.tags, dataset: stopped, ...r });
    } catch (e) { this.fail(`could not stop recording: ${e}`); }
  }

  /** Batched so a 250 Hz stream is not one POST per sample. On failure the batch is put
   *  BACK -- a dropped batch is a hole in the record that nothing downstream can see. */
  _store(vals) {
    if (this._noStore) return;
    (this._pending ??= []).push(...vals);
    if (!this.state.stamp) return;              // buffered until the store has opened the session
    if (this._pending.length < Math.max(64, this.state.rate || 250)) return;
    this._flush();
  }

  /** Send everything buffered, IN ORDER. Appends are chained, never concurrent: the server is
   *  threaded, and two batches racing each other would write samples out of order. */
  _flush() {
    this._appendChain ??= Promise.resolve();
    this._appendChain = this._appendChain.then(async () => {
      const s = this.state;
      if (!s.stamp || !this._pending || !this._pending.length) return;
      const batch = this._pending; this._pending = [];
      try {
        const r = await fetch(this._url2('dataset/append'), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stamp: s.stamp, values: batch }),
        });
        if (!r.ok) throw new Error(r.statusText);
      } catch (e) {
        this._pending = batch.concat(this._pending);
        this.fail(`samples not yet stored (${e}); retrying with the next batch`);
      }
    });
    return this._appendChain;
  }

  /* ------------------------------------------------------------------------ tagging */
  /** Tag the moment. `t_s` is the SAMPLE COUNTER, never Date.now() -- the sample index is
   *  the only clock the browser and the port-owning daemon share. */
  async tag(label) {
    const s = this.state;
    if (!s.recording) return null;
    label = String(label ?? this.$('taglabel').value ?? '').trim();
    if (!label) return null;
    const t_s = s.rate ? (s.total - s.recordStart) / s.rate : 0;
    const rec = { label, t_s };
    if (s.stamp) {
      const r = await fetch(this._url2('dataset/tag'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stamp: s.stamp, label, t_s }),
      }).then((x) => x.json()).catch((e) => ({ error: String(e) }));
      if (r.error) { this.fail(r.error); return null; }
    }
    s.tags.push(rec);
    if (!s.quick.includes(label) && s.quick.length < MAX_QUICK) {
      s.quick.push(label);
      this.renderQuick();
    }
    this.$('taglabel').select();
    this._emit('signal-tag', rec);
    return rec;
  }

  renderQuick() {
    this.$('quick').innerHTML = this.state.quick.map((l, i) =>
      `<button class="ui-btn ui-btn--ghost sp-quickbtn" data-q="${i}">`
      + `<kbd>${i + 1}</kbd>${l.replace(/</g, '&lt;')}</button>`).join('');
    for (const b of this.querySelectorAll('.sp-quickbtn')) {
      b.onclick = () => this.tag(this.state.quick[+b.dataset.q]);
    }
  }

  fail(msg) {
    this.state.error = msg || null;
    const b = this.$('banner');
    b.textContent = msg || '';
    b.hidden = !msg;
  }

  /* ---------------------------------------------------------------------------- drawing */
  draw() {
    const s = this.state;
    const c = this.$('trace');
    if (!c || !c.clientWidth) return;
    const r = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * r)) { c.width = Math.round(w * r); c.height = Math.round(h * r); }
    const g = c.getContext('2d');
    g.setTransform(r, 0, 0, r, 0, 0);
    g.clearRect(0, 0, w, h);

    const windowSamples = s.rate ? Math.round(s.window * s.rate) : s.filled;
    let x = this.recent(Math.min(s.filled, windowSamples || s.filled));
    // RULE 4. The grid is drawn whether or not there is a signal, so an empty panel reads as
    // "connected, nothing arriving" rather than as a broken widget.
    g.strokeStyle = css('--border', this); g.lineWidth = 1;
    const DIVX = 10, DIVY = 8;
    g.beginPath();
    for (let i = 1; i < DIVX; i++) { g.moveTo(w * i / DIVX, 0); g.lineTo(w * i / DIVX, h); }
    for (let i = 1; i < DIVY; i++) { g.moveTo(0, h * i / DIVY); g.lineTo(w, h * i / DIVY); }
    g.stroke();
    if (!x.length) return;

    if (s.filter) x = displayFilter(x, s.rate || 250);

    let lo = s.scale ? -s.scale : Infinity, hi = s.scale ? s.scale : -Infinity;
    if (!s.scale) {
      for (const v of x) { if (v < lo) lo = v; if (v > hi) hi = v; }
      if (!(hi > lo)) hi = lo + 1;
      const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    }

    g.strokeStyle = css('--series-measured', this) || css('--foreground', this);
    g.lineWidth = 1;
    g.beginPath();
    const step = Math.max(1, Math.floor(x.length / (w * 2)));
    for (let i = 0, k = 0; i < x.length; i += step, k++) {
      const px = (i / (x.length - 1)) * w;
      const py = h - ((x[i] - lo) / (hi - lo)) * h;
      k ? g.lineTo(px, py) : g.moveTo(px, py);
    }
    g.stroke();

    // The axes, in words. An autoscaled trace with no scale invites reading amplitude off a
    // picture, and on this rig amplitude is the thing least safe to read that way.
    g.fillStyle = css('--faint-foreground', this) || css('--foreground', this);
    g.font = '10px ui-monospace, monospace';
    const secs = s.rate ? x.length / s.rate : 0;
    g.fillText(`${((hi - lo) / DIVY).toPrecision(3)} /div`, 4, 11);
    g.fillText(`${(secs / DIVX).toPrecision(3)} s/div${s.filter ? ' · 1-45 Hz display filter (cosmetic)' : ''}`, 4, h - 4);
  }

  /** The tag track, on its own canvas glued under the trace so a mark lines up with the
   *  sample it was made at. Two canvases and one column on purpose: one canvas would mean
   *  redrawing every tag at 10 Hz for no reason. */
  drawTimeline() {
    const c = this.$('timeline');
    if (!c || !c.clientWidth) return;
    const s = this.state;
    const r = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * r)) { c.width = Math.round(w * r); c.height = Math.round(h * r); }
    const g = c.getContext('2d');
    g.setTransform(r, 0, 0, r, 0, 0);
    g.clearRect(0, 0, w, h);
    const now = s.rate ? (s.total - (s.recording ? s.recordStart : 0)) / s.rate : 0;
    const t0 = Math.max(0, now - RING_S), t1 = Math.max(RING_S, now);
    g.strokeStyle = css('--border', this); g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, h - 15); g.lineTo(w, h - 15); g.stroke();
    g.fillStyle = css('--faint-foreground', this) || css('--foreground', this);
    g.font = '10px ui-monospace, monospace';
    for (let sec = Math.ceil(t0 / 10) * 10; sec <= t1; sec += 10) {
      const px = ((sec - t0) / (t1 - t0)) * w;
      g.fillText(`${Math.round(sec)}s`, px + 2, h - 4);
      g.beginPath(); g.moveTo(px, h - 19); g.lineTo(px, h - 11); g.stroke();
    }
    const palette = ['--series-measured', '--series-predicted', '--series-spec', '--accent'];
    for (const t of s.tags) {
      if (t.t_s < t0) continue;
      const px = ((t.t_s - t0) / (t1 - t0)) * w;
      const col = css(palette[s.quick.indexOf(t.label) % palette.length], this)
        || css('--foreground', this);
      g.strokeStyle = col; g.lineWidth = 2;
      g.beginPath(); g.moveTo(px, 3); g.lineTo(px, h - 19); g.stroke();
      g.fillStyle = col;
      g.fillText(t.label.slice(0, 16), px + 3, 11);
    }
  }

  drawReadout(extra) {
    // A host's extra fields are remembered, so the panel's own redraw does not wipe them.
    if (extra !== undefined) this._readoutExtra = extra;
    const s = this.state;
    const ro = this.$ && this.$('readout');
    if (!ro) return;
    const stale = performance.now() - s.lastSampleAt > 5000;
    const q = s.quality || {};
    const alpha = alphaSnrOf(q);
    // What the bridge's /quality measures is a HEURISTIC on the signal (amplitude, mains share,
    // alpha), not electrode impedance. The row says so rather than saying "contact".
    const method = escText(q.method || 'plausibility heuristic');
    const rows = [
      ['source', s.connected ? (s.demo ? 'synthetic' : escText(this.$('port').value)) : 'not connected',
       !s.connected],
      // DECLARED and MEASURED are different numbers and are labelled as such, always.
      ['rate (declared)', s.rate ? `${s.rate.toFixed(1)} Hz` : '—', !s.rate],
      ['rate (measured)', s.rateMeasured
        ? `${Number(s.rateMeasured).toFixed(3)} Hz`
          + (s.rateErrorPpm != null ? ` (${Number(s.rateErrorPpm).toFixed(0)} ppm)` : '')
        : (s.connected ? 'not yet measured (~30 s)' : '—'), !s.rateMeasured],
      [`signal (${method})`, q.level
        ? `<span title="A heuristic on the signal, not an impedance measurement">${escText(q.level)}</span>`
        : '—', !q.level || q.level === 'unusable'],
      ...(alpha !== null ? [['alpha SNR', `${alpha.toFixed(2)} ${betaBadge()}`, false]] : []),
      ['recording', s.recording
        ? `${((s.total - s.recordStart) / (s.rate || 1)).toFixed(0)} s` : 'no', false],
      ...(s.recording || s.tags.length ? [['tags', s.tags.length
        ? `${s.tags.length} — ` + s.quick.map((l) =>
            `${escText(l)} ×${s.tags.filter((t) => t.label === l).length}`).join(', ')
        : 'none yet', !s.tags.length]] : []),
      ...Object.entries(this._readoutExtra || {}).map(([k, v]) => [k, v, false]),
    ];
    // RULE 3: dimmed, never removed.
    ro.innerHTML = rows.map(([k, v, idle]) =>
      `<dt>${k}</dt><dd class="${idle || stale ? 'is-idle' : ''}">${v}</dd>`).join('');
    const t = this.$('tier');
    if (s.demo === null) { t.hidden = true; } else {
      t.hidden = false; t.setAttribute('tier', s.demo ? 'MODELLED' : 'MEASURED');
    }
  }

  /* -------------------------------------------------------------------------- atlas tab */
  /* A host may decide LATE whether to offer the Atlas (the workbench asks the server whether the
   * atlas tool is installed first), so the attribute is observed rather than read once. */
  static get observedAttributes() { return ['atlas']; }

  attributeChangedCallback(name) {
    if (name === 'atlas' && this.$) this._setupTabs();
  }

  _setupTabs() {
    const hasAtlas = this.hasAttribute('atlas');
    const tabs = this.$('tabs');
    tabs.hidden = !hasAtlas;
    if (!hasAtlas) return;
    tabs.querySelectorAll('button').forEach((b) => {
      b.onclick = () => this._selectTab(b.dataset.tab);
    });
  }

  async _selectTab(name) {
    this.$('tabs').querySelectorAll('button').forEach((b) =>
      b.setAttribute('aria-selected', String(b.dataset.tab === name)));
    this.$('panel-monitor').hidden = name !== 'monitor';
    const atlasPanel = this.$('panel-atlas');
    atlasPanel.hidden = name !== 'atlas';
    if (name === 'atlas' && !this._atlasEl) {
      // Dynamic import: a host that never uses the atlas attribute pays nothing for this file.
      // The file comes from the optional auditory-atlas tool; the HOST maps it to
      // this URL. If it is not there, say so in the tab rather than failing silently.
      try {
        await import(new URL('./atlas-panel.js', import.meta.url));
      } catch (e) {
        atlasPanel.textContent = 'The Atlas is not installed here (optional auditory-atlas tool). ' + e;
        return;
      }
      // The whole tab is experimental: say so above it, where it cannot be scrolled past.
      const warn = document.createElement('p');
      warn.className = 'ui-rule ui-rule--exploring sp-beta-note';
      warn.innerHTML = `${betaBadge()} The Atlas plans and predicts from companion analysis `
        + 'tools. Nothing in it is an established method for this hardware, and a prediction '
        + 'here is not a measurement.';
      atlasPanel.appendChild(warn);
      this._atlasEl = document.createElement('signal-panel-atlas');
      this._atlasEl.setAttribute('bridge', this.bridge);
      atlasPanel.appendChild(this._atlasEl);
    }
  }
}

const TEMPLATE = `
<div class="sp-tabs ui-tabs" data-el="tabs" hidden>
  <button data-tab="monitor" aria-selected="true">Monitor</button>
  <button data-tab="atlas" aria-selected="false">Atlas ${betaBadge()}</button>
</div>
<div data-el="panel-monitor">
  <div class="sp-bar ui-row">
    <label class="ui-field"><span class="ui-label">Device</span>
      <select data-el="port" aria-label="serial port"></select></label>
    <label class="ui-field"><span class="ui-label">µV/count</span>
      <input data-el="uvpc" size="5"></label>
    <label class="ui-field"><span class="ui-label">Mains</span>
      <select data-el="mains"><option value="60">60 Hz</option><option value="50">50 Hz</option></select></label>
    <button class="ui-btn ui-btn--primary" data-el="connect">Connect</button>
    <button class="ui-btn" data-el="record" disabled>Record</button>
    <button class="ui-btn ui-btn--ghost" data-el="rescan" title="rescan USB">Rescan</button>
    <ui-tier data-el="tier" hidden></ui-tier>
  </div>
  <p class="ui-rule ui-rule--refuted sp-banner" data-el="banner" hidden></p>
  <figure class="sp-scope" data-el="scope">
    <div class="ui-row" style="justify-content:flex-end;gap:var(--space-2);margin-bottom:6px">
      <label class="ui-field"><span class="ui-label">Window</span>
        <select data-el="win">
          <option value="2">2 s</option><option value="5" selected>5 s</option>
          <option value="10">10 s</option><option value="30">30 s</option>
        </select></label>
      <label class="ui-field"><span class="ui-label">Scale</span>
        <select data-el="scale">
          <option value="0">auto</option><option value="50">±50 µV</option>
          <option value="200">±200 µV</option><option value="1000">±1000 µV</option>
        </select></label>
      <label class="ui-field" style="flex-direction:row;align-items:center;gap:6px">
        <input type="checkbox" data-el="filt" checked> 1-45 Hz</label>
    </div>
    <canvas data-el="trace" aria-label="live signal from the electrode"></canvas>
    <canvas data-el="timeline" aria-label="tag timeline"></canvas>
  </figure>
  <div class="sp-tagbar" data-el="tagbar" hidden>
    <div class="sp-tagfield">
      <input data-el="taglabel" placeholder="what just happened?" autocomplete="off"
             aria-label="tag label">
      <button class="ui-btn ui-btn--primary sp-tagbtn" data-el="tagbtn">
        Tag<kbd>&crarr;</kbd></button>
    </div>
    <div class="sp-quick" data-el="quick"></div>
  </div>
  <dl class="ui-readout" data-el="readout"></dl>
  <div class="sp-grid2" data-el="analysis">
    <div>
      <h3 class="ui-label">Spectrum</h3>
      <canvas data-el="spec" class="sp-spec"></canvas>
      <div data-el="bands" style="margin-top:var(--space-3)"></div>
    </div>
    <div data-el="widgetcol">
      <h3 class="ui-label">Widgets</h3>
      <div class="sp-widgets" data-el="widgets"></div>
    </div>
  </div>
</div>
<div data-el="panel-atlas" hidden></div>`;

if (!customElements.get('signal-panel')) customElements.define('signal-panel', SignalPanel);
