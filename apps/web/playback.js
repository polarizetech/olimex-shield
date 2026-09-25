/* playback.js -- play a recorded session back against its own tag track.
 *
 * The pure helpers at the top are exported and tested in node (dev_check_js.mjs); the Player
 * below draws them. Nothing here computes a physiological number -- it draws the samples that
 * were stored, at the rate that was stored, and marks the tags where they were stored.
 *
 * *** WHICH RATE, AND WHY IT IS SAID ON SCREEN. ***
 * Tags were timed on the SAMPLE counter at the declared rate (`rate_hz`), so the declared rate
 * is the only one that puts a tag back on the sample it was made at. `effective_rate_hz` is
 * wall-clock and is contaminated by a throttled tab; `rate_measured_hz` is the bridge's
 * host-clock measurement of the board. Playback uses rate_hz and prints all three.
 *
 * *** AN OVERVIEW IS MIN/MAX PER PIXEL, NEVER A STRIDE. ***
 * Taking every Nth sample to fit a long session into a strip deletes exactly the spikes an
 * operator scrubs for. Each column is the min and max of its span.
 *
 * setInterval, not requestAnimationFrame: rAF stops in a background tab and does not run in
 * a headless verification pane at all.
 */

/** Seconds -> sample index, clamped to the record. */
export function indexAt(t, rate, n) {
  return Math.max(0, Math.min(n, Math.round(t * rate)));
}

/** Min/max envelope with `cols` columns. Returns [{min, max}] -- every sample lands in a column. */
export function envelope(values, cols) {
  const n = values.length;
  const out = [];
  if (!n || cols <= 0) return out;
  const per = n / cols;
  for (let c = 0; c < cols; c++) {
    const a = Math.floor(c * per), b = Math.max(a + 1, Math.floor((c + 1) * per));
    let lo = Infinity, hi = -Infinity;
    for (let i = a; i < Math.min(b, n); i++) {
      const v = values[i];
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    if (lo !== Infinity) out.push({ min: lo, max: hi });
  }
  return out;
}

/** The tag after / before time t (strictly), or null. */
export function nextTag(tags, t) {
  return [...tags].sort((a, b) => a.t_s - b.t_s).find((x) => x.t_s > t + 1e-9) || null;
}
export function prevTag(tags, t) {
  return [...tags].sort((a, b) => b.t_s - a.t_s).find((x) => x.t_s < t - 0.25) || null;
}

/** Robust vertical scale for a window: median-centred, 1st..99th percentile span. A single
 *  blink should not flatten the rest of the trace, and an autoscale that chases it does. */
export function robustRange(values) {
  if (!values.length) return { mid: 0, half: 1 };
  const s = Float64Array.from(values).sort();
  const q = (p) => s[Math.min(s.length - 1, Math.max(0, Math.floor(p * (s.length - 1))))];
  const mid = q(0.5);
  const half = Math.max(Math.abs(q(0.99) - mid), Math.abs(mid - q(0.01)), 1e-9) * 1.15;
  return { mid, half };
}

export function fmtTime(t) {
  const m = Math.floor(t / 60), s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

const css = (v) => getComputedStyle(document.body).getPropertyValue(v).trim();

function fitCanvas(c) {
  const r = c.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(1, Math.round((r.width || c.clientWidth || 600) * dpr));
  const h = Math.max(1, Math.round((r.height || c.clientHeight || 120) * dpr));
  if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
  return { w, h, dpr };
}

export class Player {
  constructor(els) {
    this.els = els;               // {overview, trace, clock, play, prev, next, speed, window, tags}
    this.session = null;
    this.t = 0;
    this.playing = false;
    this._timer = null;
    this._last = 0;
    els.play.onclick = () => this.toggle();
    els.next.onclick = () => { const x = nextTag(this.tags, this.t); if (x) this.seek(x.t_s - 0.5); };
    els.prev.onclick = () => { const x = prevTag(this.tags, this.t); if (x) this.seek(x.t_s - 0.5); };
    els.overview.onclick = (e) => {
      const r = els.overview.getBoundingClientRect();
      this.seek(((e.clientX - r.left) / r.width) * this.duration);
    };
    for (const k of ['speed', 'window']) els[k].onchange = () => this.draw();
  }

  get tags() { return (this.session && this.session.tags) || []; }
  get rate() { return this.session ? this.session.rate : 0; }
  get duration() { return this.session ? this.session.values.length / this.rate : 0; }

  load(session) {
    this.stop();
    const meta = session.meta || {};
    this.session = { values: session.values || [], tags: session.tags || [],
                     rate: Number(meta.rate_hz) || Number(session.rate_hz) || 250, meta };
    this._env = null;
    this.t = 0;
    this.draw();
  }

  seek(t) {
    this.t = Math.max(0, Math.min(this.duration, t));
    this.draw();
    this.els.onseek && this.els.onseek(this.t);
  }

  toggle() { return this.playing ? this.stop() : this.play(); }

  play() {
    if (!this.session) return;
    if (this.t >= this.duration - 0.01) this.t = 0;
    this.playing = true;
    this.els.play.textContent = 'Pause';
    this._last = performance.now();
    this._timer = setInterval(() => {
      const now = performance.now();
      this.t += ((now - this._last) / 1000) * (+this.els.speed.value || 1);
      this._last = now;
      if (this.t >= this.duration) { this.t = this.duration; this.stop(); }
      this.draw();
    }, 50);
  }

  stop() {
    this.playing = false;
    clearInterval(this._timer);
    if (this.els.play) this.els.play.textContent = 'Play';
  }

  draw() {
    if (!this.session) return;
    this._drawOverview();
    this._drawTrace();
    this.els.clock.textContent = `${fmtTime(this.t)} / ${fmtTime(this.duration)}`;
    const cur = prevTag(this.tags, this.t + 0.26);
    for (const li of this.els.tags.children) {
      li.setAttribute('aria-current', cur && +li.dataset.t === cur.t_s ? 'true' : 'false');
    }
  }

  _drawOverview() {
    const c = this.els.overview, g = c.getContext('2d');
    const { w, h } = fitCanvas(c);
    const v = this.session.values;
    if (!this._env || this._env.length !== w) this._env = envelope(v, w);
    const { mid, half } = robustRange(v);
    const y = (x) => h / 2 - ((x - mid) / half) * (h / 2 - 2);
    g.clearRect(0, 0, w, h);
    g.fillStyle = css('--card');
    g.fillRect(0, 0, w, h);
    g.strokeStyle = css('--series-1') || css('--foreground');
    g.beginPath();
    this._env.forEach((e, i) => { g.moveTo(i + 0.5, y(e.max)); g.lineTo(i + 0.5, y(e.min)); });
    g.stroke();
    g.strokeStyle = css('--accent') || css('--foreground');
    for (const t of this.tags) {
      const x = (t.t_s / this.duration) * w;
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
    }
    g.fillStyle = css('--foreground');
    g.fillRect((this.t / this.duration) * w - 1, 0, 2, h);
  }

  _drawTrace() {
    const c = this.els.trace, g = c.getContext('2d');
    const { w, h, dpr } = fitCanvas(c);
    const win = +this.els.window.value || 5, rate = this.rate, v = this.session.values;
    const t0 = Math.max(0, this.t - win);
    const a = indexAt(t0, rate, v.length), b = indexAt(this.t, rate, v.length);
    const seg = v.slice(a, Math.max(b, a + 1));
    const { mid, half } = robustRange(seg.length > 8 ? seg : v.slice(0, rate * win));
    const y = (x) => h / 2 - ((x - mid) / half) * (h / 2 - 12 * dpr);
    g.clearRect(0, 0, w, h);
    g.fillStyle = css('--card'); g.fillRect(0, 0, w, h);
    g.strokeStyle = css('--border'); g.lineWidth = 1;
    for (let i = 1; i < win; i++) {
      const x = (i / win) * w; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
    }
    for (let i = 1; i < 4; i++) {
      const yy = (i / 4) * h; g.beginPath(); g.moveTo(0, yy); g.lineTo(w, yy); g.stroke();
    }
    g.strokeStyle = css('--series-1') || css('--foreground'); g.lineWidth = 1.2 * dpr;
    g.beginPath();
    const span = win * rate;
    seg.forEach((val, i) => {
      const x = ((a + i - (this.t - win) * rate) / span) * w;
      i ? g.lineTo(x, y(val)) : g.moveTo(x, y(val));
    });
    g.stroke();
    g.fillStyle = css('--foreground'); g.strokeStyle = css('--accent') || css('--foreground');
    g.font = `${11 * dpr}px ${css('--font-mono') || 'monospace'}`;
    for (const t of this.tags) {
      if (t.t_s < this.t - win || t.t_s > this.t) continue;
      const x = ((t.t_s - (this.t - win)) / win) * w;
      g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke();
      g.fillText(t.label, x + 3 * dpr, 13 * dpr);
    }
    // The trace says what its axes are (a picture of an amplitude is not a measurement).
    const unit = this.session.meta.already_uv ? 'µV' : 'counts';
    g.fillStyle = css('--muted-foreground') || css('--foreground');
    g.fillText(`${(half * 2 / 4).toPrecision(3)} ${unit}/div · 1 s/div · ${rate} Hz declared`,
               6 * dpr, h - 6 * dpr);
  }
}
