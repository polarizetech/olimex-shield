/*
 * eeg-client.js — drop-in browser client for the shared EEG Bridge.
 *
 * Usage (any page that can reach the bridge):
 *     <script src="http://localhost:8140/eeg-client.js"></script>   // or copy the file in
 *     const eeg = new EEGClient({ base: 'http://localhost:8140' });
 *     await eeg.connect();                 // finds a device and opens it (idempotent)
 *     eeg.onData(() => { ... });           // fires as samples arrive
 *     eeg.bands();                         // EXPERIMENTAL; prefer POST /bands
 *     eeg.iaf();                           // EXPERIMENTAL; alpha peak (Hz) or null
 *     eeg.scope(canvas);                   // draw a live trace
 *
 * Honesty, carried from the corpus: this gives you a READ. It does not validate anything about what the
 * audio is doing. A closed loop built on it is still an inference chain — EEG → band power → "state" —
 * and band power is a noisy, artefact-prone proxy (jaw clench and blinks move alpha too). Treat any
 * effect claim as [C]/[SPEC] until you have a proper artefact-rejected, baseline-controlled measurement.
 */
(function (root) {
  'use strict';

  // NOTE: this file's bands() and the service's POST /bands are TWO implementations of the same
  // quantity in two languages. The SERVER one is authoritative — it is stdlib Python covered by
  // dev_check.py. This client-side version stays because clients already call it and it needs no
  // round trip; it now uses the server's method (Hann window, SUM of the exact DFT bins in each
  // half-open band [lo, hi)), so the relative shares agree. Prefer POST /bands whenever the
  // number will be REPORTED rather than drawn. The workbench's <signal-panel> uses the server.
  const BANDS = {
    delta: [1, 4], theta: [4, 8], alpha: [8, 13], beta: [13, 30], gamma: [30, 45]
  };

  class EEGClient {
    constructor(opts) {
      opts = opts || {};
      this.base = (opts.base || 'http://localhost:8140').replace(/\/$/, '');
      this.rate = opts.rate || 250;              // nominal; refined from /status
      this.ringSec = opts.ringSec || 8;
      this.ring = new Float32Array(this.rate * this.ringSec);
      this.w = 0;                                 // write cursor
      this.filled = 0;
      this.total = 0;                             // last server sample index seen
      this.generation = null;
      this.connected = false;
      this.lastError = null;
      this.gaps = 0;
      this._es = null;
      this._cbs = [];
    }

    async status() {
      const r = await fetch(this.base + '/status', { cache: 'no-store' });
      return r.json();
    }
    async ports() {
      const r = await fetch(this.base + '/ports', { cache: 'no-store' });
      return r.json();
    }

    /** Open a device (idempotent server-side) and start streaming. */
    async connect(opts) {
      opts = opts || {};
      const st = await this.status();
      if (!st.supported) {
        this.lastError = 'pyserial missing on the bridge — falling back is up to the caller';
        throw new Error(this.lastError);
      }
      this.rate = st.rate || this.rate;
      if (!st.open) {
        const r = await fetch(this.base + '/open', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ port: opts.port, baud: opts.baud || 115200, channelCol: opts.channelCol ?? 1 })
        });
        const j = await r.json();
        if (j.error) { this.lastError = j.error; throw new Error(j.error); }
        this.total = j.total || 0;
      } else {
        this.total = st.total || 0;               // reattach to a session already running
      }
      this._subscribe();
      this.connected = true;
      return this.status();
    }

    _subscribe() {
      if (this._es) this._es.close();
      const es = new EventSource(this.base + '/stream?from=' + this.total);
      es.onmessage = (e) => {
        let d; try { d = JSON.parse(e.data); } catch { return; }
        if (!d.samples) return;
        if (this.generation !== null && d.generation !== this.generation) this.reset();
        this.generation = d.generation;
        if (d.from > this.total) this.gaps++;      // fell behind the ring — samples were dropped
        this.total = d.total;
        for (let i = 0; i < d.samples.length; i++) {
          this.ring[this.w] = d.samples[i];
          this.w = (this.w + 1) % this.ring.length;
          if (this.filled < this.ring.length) this.filled++;
        }
        // One subscriber throwing must not starve the others or kill the stream handler.
        this._cbs.forEach(f => { try { f(this); } catch { /* isolate subscriber errors */ } });
      };
      es.onerror = () => { this.lastError = 'stream dropped'; };
      this._es = es;
    }

    onData(fn) { this._cbs.push(fn); return this; }
    reset() { this.ring.fill(0); this.w = 0; this.filled = 0; }
    disconnect() { if (this._es) this._es.close(); this._es = null; this.connected = false; }

    /** Most recent n samples, oldest→newest. */
    recent(n) {
      n = Math.min(n || this.filled, this.filled);
      const out = new Float32Array(n);
      for (let i = 0; i < n; i++) out[i] = this.ring[(this.w - n + i + this.ring.length) % this.ring.length];
      return out;
    }

    /** Goertzel power at one frequency. */
    _goertzel(x, f) {
      const w = 2 * Math.PI * f / this.rate, c = 2 * Math.cos(w);
      let s0 = 0, s1 = 0, s2 = 0;
      for (let i = 0; i < x.length; i++) { s0 = x[i] + c * s1 - s2; s2 = s1; s1 = s0; }
      return s1 * s1 + s2 * s2 - c * s1 * s2;
    }

    /** Mean-removed, Hann-windowed copy of the last n samples (the server's preparation). */
    _prepared(n) {
      const x = this.recent(n);
      let mean = 0; for (let i = 0; i < n; i++) mean += x[i]; mean /= n;
      for (let i = 0; i < n; i++) x[i] = (x[i] - mean) * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)));
      return x;
    }

    /** Summed power of the exact DFT bins k with lo <= k*rate/n < hi (as quality.band_power). */
    _bandSum(x, lo, hi) {
      const n = x.length;
      const kLo = Math.max(1, Math.ceil(lo * n / this.rate - 1e-9));
      const kHi = Math.min(Math.floor(n / 2) - 1, Math.ceil(hi * n / this.rate - 1e-9) - 1);
      let p = 0;
      for (let k = kLo; k <= kHi; k++) p += this._goertzel(x, k * this.rate / n);
      return p;
    }

    /**
     * Band powers over the last `sec` seconds.
     *
     * @deprecated EXPERIMENTAL and duplicated: POST /bands on the bridge is authoritative. Kept
     * because existing pages call it. Same method as the server (Hann window, sum of exact DFT
     * bins in half-open bands), so `…Rel` agrees with /bands; the absolute numbers are bin sums
     * in counts² and mean nothing on their own. Band power is a proxy that blinks and jaw clench
     * move convincingly.
     */
    bands(sec) {
      const n = Math.min(Math.floor((sec || 4) * this.rate), this.filled);
      if (n < this.rate) return null;                     // need ≥1 s
      const x = this._prepared(n);
      const out = {}; let tot = 0;
      for (const k in BANDS) {
        const [lo, hi] = BANDS[k];
        out[k] = this._bandSum(x, lo, hi); tot += out[k];
      }
      out.total = tot;                                    // == sum over 1–45 Hz: bands partition it
      for (const k in BANDS) out[k + 'Rel'] = tot > 0 ? out[k] / tot : 0;
      out.experimental = true;
      return out;
    }

    /**
     * Individual alpha peak (7–13 Hz), or null.
     *
     * @deprecated EXPERIMENTAL: not computed by the server and not validated on this hardware.
     * Returns null unless the maximum is a TRUE local peak -- strictly higher than both
     * neighbouring 0.1 Hz steps and not at either edge of the 7–13 Hz scan. A monotonic slope
     * (the usual 1/f background) has its maximum at an edge, and that is not an alpha peak.
     */
    iaf(sec) {
      const n = Math.min(Math.floor((sec || 6) * this.rate), this.filled);
      if (n < this.rate * 2) return null;
      const x = this._prepared(n);
      const fs = [], ps = [];
      for (let i = 0; i <= 60; i++) { const f = 7 + i * 0.1; fs.push(f); ps.push(this._goertzel(x, f)); }
      let best = -1;
      for (let i = 0; i < ps.length; i++) if (best < 0 || ps[i] > ps[best]) best = i;
      if (best <= 0 || best >= ps.length - 1) return null;
      if (!(ps[best] > ps[best - 1] && ps[best] > ps[best + 1])) return null;
      return Math.round(fs[best] * 10) / 10;
    }

    /** Live trace onto a canvas. */
    scope(canvas, opts) {
      opts = opts || {};
      const ctx = canvas.getContext('2d'), W = canvas.width, H = canvas.height;
      const n = Math.min(Math.floor((opts.sec || 4) * this.rate), this.filled);
      ctx.fillStyle = opts.bg || '#0b0e14'; ctx.fillRect(0, 0, W, H);
      if (n < 2) {
        ctx.fillStyle = '#4A5364'; ctx.font = '12px monospace';
        ctx.fillText('no signal', 10, H / 2); return;
      }
      const x = this.recent(n);
      let mn = Infinity, mx = -Infinity;
      for (let i = 0; i < n; i++) { if (x[i] < mn) mn = x[i]; if (x[i] > mx) mx = x[i]; }
      const span = (mx - mn) || 1;
      ctx.strokeStyle = opts.color || '#5FD3D0'; ctx.lineWidth = 1.4; ctx.beginPath();
      for (let i = 0; i < W; i++) {
        const v = x[Math.floor(i / W * n)];
        const y = H - ((v - mn) / span) * (H * 0.9) - H * 0.05;
        i ? ctx.lineTo(i, y) : ctx.moveTo(i, y);
      }
      ctx.stroke();
    }
  }

  root.EEGClient = EEGClient;
  root.EEG_BANDS = BANDS;
})(typeof window !== 'undefined' ? window : globalThis);
