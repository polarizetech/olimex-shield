/* session-recorder.js — the browser half of the durability contract.
 *
 * Served from the bridge (like eeg-client.js) so every client shares ONE copy and they cannot
 * drift. Ported from an earlier internal project's FailsafeStore + SessionStreamer, which had this
 * right and had it trapped inside one app.
 *
 * WHY A BROWSER LAYER EXISTS AT ALL, given the server already writes to disk:
 * they fail in OPPOSITE directions. The server-side writer survives the browser dying (tab close,
 * crash, reload). This survives the SERVER dying (process killed, port lost, network gone, disk
 * full). Neither is redundant with the other, and a session that loses both was never recoverable.
 *
 * IndexedDB, not localStorage — localStorage blows its ~5 MB cap on a few minutes of raw samples,
 * and it blows it SILENTLY mid-session, which is the worst possible time to find out.
 *
 * Every write here is fire-and-forget and swallows its own errors. THE FAILSAFE MUST NEVER BREAK A
 * LIVE SESSION: a durability layer that throws during recording has destroyed the thing it exists
 * to protect.
 */

// Legacy database name from the bridge's earlier name, kept so existing failsafe data is found.
const DB_NAME = 'eeg-bridge-failsafe', DB_VERSION = 1;

function openDb() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === 'undefined') return reject(new Error('no IndexedDB'));
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains('sessions')) db.createObjectStore('sessions', { keyPath: 'id' });
      if (!db.objectStoreNames.contains('chunks')) {
        db.createObjectStore('chunks', { keyPath: 'key', autoIncrement: true })
          .createIndex('bySession', 'sessionId', { unique: false });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}
const store = (db, n, m) => db.transaction(n, m).objectStore(n);
const done = (r) => new Promise((res, rej) => { r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });

/** L3 — the browser failsafe. Survives the server going away entirely. */
export class FailsafeStore {
  constructor() { this._db = null; this._ok = true; }
  async _get() {
    if (!this._db && this._ok) { try { this._db = await openDb(); } catch { this._ok = false; } }
    return this._db;
  }
  get available() { return this._ok; }

  async startSession(id, meta = {}) {
    const db = await this._get(); if (!db) return;
    const iso = new Date().toISOString();
    try {
      await done(store(db, 'sessions', 'readwrite').put({
        id, status: 'in_progress', started_at: iso, updated_at: iso, meta, record: null,
        rows_total: 0, phase: 'pre_session',
      }));
    } catch { /* never break a live session */ }
  }

  async updateSession(id, record, { rowsTotal = null, phase = null } = {}) {
    const db = await this._get(); if (!db) return;
    try {
      const s = store(db, 'sessions', 'readwrite');
      const cur = (await done(s.get(id))) || { id, status: 'in_progress', started_at: new Date().toISOString() };
      cur.record = record; cur.updated_at = new Date().toISOString();
      if (phase !== null) cur.phase = phase;
      if (rowsTotal !== null) cur.rows_total = rowsTotal;
      await done(s.put(cur));
    } catch { /* ignore */ }
  }

  /** Append-only, so the full session is never held in memory alone. */
  async appendChunk(id, chunk) {
    const db = await this._get(); if (!db || !chunk || !chunk.csvRows) return;
    try { await done(store(db, 'chunks', 'readwrite').add({ sessionId: id, ...chunk })); } catch { /* ignore */ }
  }

  async completeSession(id, record) {
    const db = await this._get(); if (!db) return;
    try {
      const s = store(db, 'sessions', 'readwrite');
      const cur = await done(s.get(id));
      if (cur) { cur.status = 'completed'; cur.record = record; cur.updated_at = new Date().toISOString(); await done(s.put(cur)); }
    } catch { /* ignore */ }
  }

  async listOrphans() {
    const db = await this._get(); if (!db) return [];
    try { return (await done(store(db, 'sessions', 'readonly').getAll())).filter(s => s.status === 'in_progress'); }
    catch { return []; }
  }

  async getChunks(id) {
    const db = await this._get(); if (!db) return [];
    try { return await done(store(db, 'chunks', 'readonly').index('bySession').getAll(id)); }
    catch { return []; }
  }

  /** Export a recovered orphan as a downloadable JSON blob. The operator decides, not us. */
  async exportOrphan(id) {
    const db = await this._get(); if (!db) return null;
    const s = await done(store(db, 'sessions', 'readonly').get(id));
    if (!s) return null;
    return { ...s, chunks: await this.getChunks(id), recovered_from: 'indexeddb_failsafe' };
  }

  async discard(id) {
    const db = await this._get(); if (!db) return;
    try {
      await done(store(db, 'sessions', 'readwrite').delete(id));
      const c = store(db, 'chunks', 'readwrite');
      for (const k of await done(c.index('bySession').getAllKeys(id))) c.delete(k);
    } catch { /* ignore */ }
  }
}

/**
 * SessionRecorder — L2 + L3 + L4 behind one object.
 *
 * Usage:
 *   const rec = new SessionRecorder({ app: 'attend-to-send', name: 'arm-a-01', base: '' });
 *   const pre = await rec.preflight();        // L2 disk self-test — CHECK THIS before a long run
 *   await rec.start({ csvHeader: 'idx,uv', meta });
 *   await rec.update(record, csvRows, 'block-3');
 *   await rec.finish(record);
 */
export class SessionRecorder {
  /** @param base URL prefix reaching the bridge — '' when same-origin-proxied at /bridge. */
  constructor({ app, name, base = '', endpoint = '/bridge' } = {}) {
    this.app = app; this.name = name;
    this.url = (p) => `${base}${endpoint}${p}`;
    this.failsafe = new FailsafeStore();
    this.id = `${app}:${name}`;
    this.rows = 0;
    this.serverOk = null;          // null = not yet attempted
    this.lastServerError = null;
    this._record = null;
    this._phase = 'pre_session';
    this._unload = null;
  }

  async _post(path, body) {
    try {
      const r = await fetch(this.url(path), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app: this.app, name: this.name, ...body }),
      });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      this.serverOk = true; this.lastServerError = null;
      return await r.json();
    } catch (e) {
      // A server write failure DOWNGRADES to failsafe-only; it never aborts the session.
      this.serverOk = false; this.lastServerError = e.message;
      return null;
    }
  }

  /** L2 pre-session disk self-test. Returns {ok, free_mb, warning, ...}. */
  async preflight() {
    const r = await this._post('/session/selftest', {});
    return r || { ok: false, error: this.lastServerError,
                  warning: 'The bridge did not answer. Only the in-browser failsafe would capture.' };
  }

  async start({ csvHeader = null, meta = {}, confirmOnUnload = true } = {}) {
    await this.failsafe.startSession(this.id, meta);
    await this._post('/session/init', { csv_header: csvHeader, meta });
    if (confirmOnUnload) this._armUnload();
    return { serverOk: this.serverOk, failsafeOk: this.failsafe.available };
  }

  async update(record, csvRows = null, phase = null) {
    this._record = record;
    if (phase) this._phase = phase;
    if (csvRows) this.rows += csvRows.length;
    // Failsafe first, deliberately: it is the layer that survives the server, so it must not be
    // skipped by an await on a server call that is about to time out.
    this.failsafe.updateSession(this.id, record, { rowsTotal: this.rows, phase: this._phase });
    if (csvRows) this.failsafe.appendChunk(this.id, { phase: this._phase, n: csvRows.length, csvRows });
    return this._post('/session/update', { record, csv_rows: csvRows, phase: this._phase });
  }

  async finish(record, { terminatedEarly = false, phase = 'complete' } = {}) {
    this._disarmUnload();
    const r = await this._post('/session/finalize',
                               { record, phase, terminated_early: terminatedEarly });
    if (!terminatedEarly) await this.failsafe.completeSession(this.id, record);
    return r;
  }

  /* ---- L4: the accidental tab close ------------------------------------------------------ */
  _armUnload() {
    this._unload = (e) => {
      // sendBeacon survives unload where fetch does not. Best-effort flush of the LAST state,
      // still flagged terminated_early — so a close mid-session leaves an honest partial record.
      try {
        navigator.sendBeacon(this.url('/session/update'), new Blob([JSON.stringify({
          app: this.app, name: this.name, record: this._record, phase: this._phase,
        })], { type: 'application/json' }));
      } catch { /* ignore */ }
      e.preventDefault();
      e.returnValue = '';        // browsers show their own generic confirm text
      return '';
    };
    window.addEventListener('beforeunload', this._unload);
  }

  _disarmUnload() {
    if (this._unload) { window.removeEventListener('beforeunload', this._unload); this._unload = null; }
  }

  /* ---- recovery -------------------------------------------------------------------------- */
  async orphans() {
    const server = await this._post('/session/orphans', {});
    return {
      server: (server && server.orphans) || [],
      browser: await this.failsafe.listOrphans(),
      serverReachable: this.serverOk,
    };
  }
}

/** Download a recovered record as a file. Nothing is auto-deleted; the operator decides. */
export function downloadRecovered(obj, filename) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url; a.download = filename || 'recovered-session.json';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
