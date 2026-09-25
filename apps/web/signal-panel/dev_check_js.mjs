/* dev_check_js.mjs -- the panel's BEHAVIOUR, in a minimal DOM. `node dev_check_js.mjs` */
let pass = 0; const fail = [];
const ok = (n, c, note = "") => c ? pass++ : fail.push(`${n}${note ? " -- " + note : ""}`);

// A DOM small enough to be honest about: enough for the ring and the gate, not a browser.
class El { constructor(){this.children=[];this.style={};this.attrs={};this.hidden=false;
    this.value="";this.innerHTML="";this.dataset={};}
  select(){} querySelectorAll(){return [];}
  setAttribute(k,v){this.attrs[k]=v;} getAttribute(k){return this.attrs[k]??null;}
  querySelector(){return new El();} addEventListener(){} appendChild(c){this.children.push(c);} }
globalThis.HTMLElement = class { constructor(){ this.innerHTML=""; this._attrs={}; }
  querySelector(){ return new El(); } querySelectorAll(){ return []; }
  getAttribute(k){ return this._attrs[k] ?? null; }
  setAttribute(k,v){ this._attrs[k]=String(v); }
  hasAttribute(k){ return k in this._attrs; }
  dispatchEvent(e){ (this._h?.[e.type]||[]).forEach(f=>f(e)); return true; }
  addEventListener(t,f){ (this._h??={})[t]??=[]; this._h[t].push(f); } };
globalThis.CustomEvent = class { constructor(t,o){ this.type=t; this.detail=o?.detail; } };
globalThis.customElements = { get: () => undefined, define: () => {} };
globalThis.document = { baseURI: "http://x/app/", body: {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "#000" });
globalThis.performance = { now: () => 0 };
globalThis.setInterval = () => 0;

const { SignalPanel } = await import("./signal-panel.js");

const p = new SignalPanel();
p.state.rate = 4; p.state.ring = new Float32Array(8);

// --- the ring, which is the one numeric thing the panel owns
for (const v of [1,2,3,4,5]) { p.state.ring[p.state.head] = v;
  p.state.head = (p.state.head+1)%8; if (p.state.filled<8) p.state.filled++; }
ok("recent() returns oldest-first", Array.from(p.recent(5)).join()==="1,2,3,4,5");
ok("recent(n) clamps to what is filled", p.recent(99).length === 5);
// wrap it past the end -- a ring read from 0 looks fine until it wraps
for (const v of [6,7,8,9,10]) { p.state.ring[p.state.head]=v;
  p.state.head=(p.state.head+1)%8; if (p.state.filled<8) p.state.filled++; }
ok("and stays oldest-first ACROSS THE WRAP",
   Array.from(p.recent(8)).join()==="3,4,5,6,7,8,9,10", Array.from(p.recent(8)).join());

// --- the consent gate actually gates
let opened = false;
globalThis.fetch = async (u) => { if (String(u).includes("/open")) opened = true;
  return { json: async () => ({}) }; };
const q = new SignalPanel();
q.$ = () => new El();
q.state.connected = false;
q.beforeConnect = async () => false;
await q.toggleConnect();
ok("beforeConnect returning false prevents the port opening", opened === false);
ok("and the panel does not mark itself connected", q.state.connected === false);

// A double click while the gate is still open must not stack a second gate.
let gates = 0, release;
const dbl = new SignalPanel();
dbl.$ = () => new El();
dbl.beforeConnect = () => { gates++; return new Promise((r) => { release = r; }); };
const first = dbl.toggleConnect();
await dbl.toggleConnect();                         // the second click, gate still open
ok("a second Connect while the gate is open does not open a second gate", gates === 1,
   String(gates));
release(false); await first;
ok("and once the first gate resolves, Connect works again", dbl._connecting === false);

// --- the tier never comes from the port name
const r = new SignalPanel();
ok("info.tier is null before a status is seen", r.info.tier === null);
r.state.demo = true;  ok("demo -> MODELLED", r.info.tier === "MODELLED");
r.state.demo = false; ok("real -> MEASURED", r.info.tier === "MEASURED");

// --- the URL is built against the HOST's mount, not an absolute bridge address
const s = new SignalPanel();
s.getAttribute = () => "bridge";
ok("routes resolve relative to the page, so the gateway mount is respected",
   s._url("open") === "http://x/app/bridge/open", s._url("open"));

// --- tagging behaviour
const t = new SignalPanel();
t.$ = () => new El();
t.state.rate = 100; t.state.total = 250;
ok("a tag is refused when not recording", await t.tag("x") === null);
t.state.recording = true;
// The clock is zeroed at RECORD, not at CONNECT. A recorded sidecar showed tags at 77 s in a
// 23 s session before this existed -- silent, and it misaligned every tag against its samples.
t.state.recordStart = 200;
globalThis.fetch = async () => ({ json: async () => ({}) });
const rec = await t.tag("looked at colour");
ok("t_s is measured from RECORD start, not from connect",
   rec && rec.t_s === 0.5, JSON.stringify(rec));
ok("the label is kept verbatim", rec && rec.label === "looked at colour");
ok("an empty label is refused", await t.tag("   ") === null);
ok("the label becomes a quick key", t.state.quick[0] === "looked at colour");
for (let i = 0; i < 12; i++) await t.tag("label" + i);
ok("quick keys stop at 9 -- there are only nine number keys",
   t.state.quick.length <= 9, String(t.state.quick.length));
ok("but every tag is still recorded", t.state.tags.length === 13, String(t.state.tags.length));

// --- 2026-09-14 merge: the widget contract and the config actually reaching the quality gate
const w = new SignalPanel();
ok("the default widget rack has the two ported widgets, each with a real run()",
   w.widgets.length === 2 && w.widgets.every((x) => typeof x.run === "function" && x.needs > 0),
   JSON.stringify(w.widgets.map((x) => x.id)));

const u = new SignalPanel();
u.$ = (id) => { const e = new El(); if (id === "uvpc") e.value = "12.3";
  if (id === "mains") e.value = "50"; return e; };
u.state.connected = true; u.state.rate = 250;
u.state.ring = new Float32Array(2000); u.state.filled = 2000;
let sentBody = null;
globalThis.fetch = async (url, opts) => { sentBody = JSON.parse(opts.body); return { ok: true, json: async () => ({}) }; };
await u.checkQuality(null, { immediate: true });
ok("checkQuality sends the CONFIGURED uv_per_count, not a hardcoded default",
   sentBody && sentBody.uv_per_count === 12.3, JSON.stringify(sentBody));
ok("...and the configured mains, not a hardcoded default",
   sentBody && sentBody.mains_hz === 50, JSON.stringify(sentBody));
ok("no cfg key is sent when there is no override", sentBody && !("cfg" in sentBody),
   JSON.stringify(sentBody));

// REGRESSION: the override was spread at the top level, and the bridge reads body["cfg"] --
// so a plant's or a limb's disabled alpha-SNR gate never reached the gate at all.
u.qualityConfig = { min_alpha_snr: 0, good_alpha_snr: 0 };
await u.checkQuality(undefined, { immediate: true });
ok("host qualityConfig is sent NESTED under cfg, where the bridge actually reads it",
   sentBody && sentBody.cfg && sentBody.cfg.min_alpha_snr === 0
   && !("min_alpha_snr" in sentBody), JSON.stringify(sentBody));

// --- stream gaps: a jump in `from` is counted and reported, never silently concatenated
let lastES = null;
globalThis.EventSource = class { constructor(u) { this.u = u; lastES = this; } close() {} };
const g = new SignalPanel();
g.$ = () => new El();
g.state.rate = 250; g.state.ring = new Float32Array(64);
const seen = [];
g.addEventListener("signal-samples", (e) => seen.push(e.detail));
g.openStream();
lastES.onmessage({ data: JSON.stringify({ from: 0, samples: [1, 2, 3] }) });
lastES.onmessage({ data: JSON.stringify({ from: 10, samples: [4] }) });   // 3..9 never arrived
ok("a jump in `from` is counted as a gap of exactly the missing samples",
   g.state.gaps === 7 && g.info.gaps === 7, String(g.state.gaps));
ok("...and the host is told on the batch that follows it",
   seen.length === 2 && seen[0].gap === 0 && seen[1].gap === 7, JSON.stringify(seen));

// --- connecting to an ALREADY-OPEN port must not replay its whole ring as live
const reopen = new SignalPanel();
reopen.$ = () => new El();
globalThis.fetch = async (u) => ({ ok: true, json: async () =>
  (String(u).includes("status") ? { total: 15000, rate: 250, demo: false } : {}) });
await reopen.toggleConnect();
ok("the stream starts 2 s back from the bridge's current total, not from sample 0",
   lastES && lastES.u.endsWith("stream?from=14500"), lastES && lastES.u);
ok("and the rate came from the bridge's `rate` key", reopen.state.rate === 250);
ok("the ring defaults to 60 s at the bridge's rate", reopen.state.ring.length === 250 * 60,
   String(reopen.state.ring.length));
const long = new SignalPanel();
long.$ = () => new El();
long.setAttribute("ring", "320");
await long.toggleConnect();
ok("ring=\"320\" sizes the ring for a host's longest capture window",
   long.state.ring.length === 250 * 320, String(long.state.ring.length));

// --- the measured rate: polled from the bridge, used for lock-in only
const rt = new SignalPanel();
rt.$ = () => new El();
rt.state.connected = true; rt.state.rate = 250;
ok("before the bridge has measured, lock-in uses the declared rate", rt.analysisRate === 250);
const rateEvents = [];
rt.addEventListener("signal-rate", (e) => rateEvents.push(e.detail));
globalThis.fetch = async () => ({ ok: true, json: async () =>
  ({ rate: 250, rateMeasured: 249.839, rateErrorPpm: -644, rateUncertaintyPpm: 2, rateBasis: "host clock" }) });
await rt._refreshRate();
ok("once measured, lock-in uses the MEASURED rate", rt.analysisRate === 249.839, String(rt.analysisRate));
ok("...but the ring/trace/tag clock keep the declared rate, so no tag moves mid-session",
   rt.state.rate === 250 && rt.info.rate === 250 && rt.info.rateMeasured === 249.839);
ok("the host is told when the measured rate appears", rateEvents.length === 1
   && rateEvents[0].errorPpm === -644, JSON.stringify(rateEvents));
await rt._refreshRate();
ok("...and not told again when nothing changed", rateEvents.length === 1);

// --- the Atlas tab bar's [hidden] state -- REGRESSION coverage for the .ui-tabs display:flex
// vs [hidden] specificity tie (found by opening a real consumer in a browser, not by this
// harness, which is exactly why _setupTabs() is exercised directly here now).
const noAtlas = new SignalPanel();
const tabsEl1 = new El();
noAtlas.$ = (id) => (id === "tabs" ? tabsEl1 : new El());
noAtlas._setupTabs();
ok("no `atlas` attribute -> the tab bar stays hidden", tabsEl1.hidden === true);

const withAtlas = new SignalPanel();
withAtlas.setAttribute("atlas", "");
const tabsEl2 = new El();
withAtlas.$ = (id) => (id === "tabs" ? tabsEl2 : new El());
withAtlas._setupTabs();
ok("the `atlas` attribute -> the tab bar is shown", tabsEl2.hidden === false);

// A host that decides late (the workbench checks the atlas tool is installed first) still gets tabs.
const late = new SignalPanel();
const tabsEl3 = new El();
late.$ = (id) => (id === "tabs" ? tabsEl3 : new El());
late._setupTabs();
ok("no atlas at connect -> hidden", tabsEl3.hidden === true);
late.setAttribute("atlas", "");
late.attributeChangedCallback("atlas");
ok("the atlas attribute added AFTER connect shows the tab bar", tabsEl3.hidden === false);
ok("the attribute is observed, not read once", SignalPanel.observedAttributes.includes("atlas"));

// --- RECORDING: REGRESSION for three silent data-loss bugs found on the real board 2026-09-15.
// (1) Stop dropped the last partial batch (1859 stored vs 2020 in the black box); (2) samples
// that arrived before the store answered `dataset/start` were dropped while the tag clock had
// already started; (3) every black box was `capture.csv`. Appends must also stay ORDERED.
{
  const calls = [];
  let release = null;
  globalThis.fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : {};
    calls.push({ url: String(url), body });
    const u = String(url);
    if (u.endsWith("bridge/record")) return { ok: true, json: async () => ({ recording: true, recPath: `/x/${body.name}.csv` }) };
    if (u.endsWith("dataset/start")) { await new Promise((r) => (release = r)); return { ok: true, json: async () => ({ stamp: "S1" }) }; }
    return { ok: true, json: async () => ({ stamp: "S1" }) };
  };
  const rp = new SignalPanel();
  rp.state.rate = 100; rp.state.connected = true;
  rp.$ = () => new El();
  rp.renderQuick = () => {};
  const started = rp.toggleRecord();
  while (!release) await new Promise((r) => setTimeout(r, 0));
  rp._store([1, 2, 3]);                 // arrives while dataset/start is still pending
  release();
  await started;
  rp._store([4, 5]);
  await rp.stopRecording();
  await rp._appendChain;
  const appended = calls.filter((c) => c.url.endsWith("dataset/append")).flatMap((c) => c.body.values);
  ok("samples that arrived before the store opened are kept", appended.slice(0, 3).join() === "1,2,3", appended.join());
  ok("the partial batch at Stop is flushed, not dropped", appended.join() === "1,2,3,4,5", appended.join());
  const order = calls.map((c) => c.url.split("/").slice(-2).join("/"));
  ok("everything is appended BEFORE the session is stopped",
     order.lastIndexOf("dataset/append") < order.indexOf("dataset/stop"), order.join(" > "));
  const rec = calls.find((c) => c.url.endsWith("bridge/record"));
  ok("the black box gets its own name, never the shared default",
     /^rec-\d{8}T\d{6}-[a-z0-9]{1,4}$/.test(rec.body.name || ""), rec.body.name);
  const startBody = calls.find((c) => c.url.endsWith("dataset/start")).body;
  ok("...and the session records which black box it is", startBody.black_box === `${rec.body.name}.csv`, startBody.black_box);

  const seen = [];
  let slow = true;
  globalThis.fetch = async (url, init = {}) => {
    const b = init.body ? JSON.parse(init.body) : {};
    if (String(url).endsWith("dataset/append")) {
      if (slow) { slow = false; await new Promise((r) => setTimeout(r, 20)); }
      seen.push(b.values[0]);
    }
    return { ok: true, json: async () => ({}) };
  };
  const op = new SignalPanel();
  op.state.stamp = "S2"; op.state.rate = 100;
  op._pending = [10]; op._flush();
  await new Promise((r) => setTimeout(r, 0));       // batch 1 is now in flight (slow)
  op._pending.push(20); op._flush();
  await op._appendChain;
  ok("appends are serialised: a slow batch is not overtaken", seen.join() === "10,20", seen.join());
}

// --- the readout: declared vs measured rate, the plausibility heuristic, the experimental badge
{
  const { alphaSnrOf } = await import("./signal-panel.js");
  ok("alphaSnrOf reads a bare number", alphaSnrOf({ alpha_snr: 3.5 }) === 3.5);
  ok("...or an experimental sub-result object",
     alphaSnrOf({ alpha_snr: { value: 4.25, experimental: true } }) === 4.25);
  ok("...and is null when absent", alphaSnrOf({ level: "good" }) === null && alphaSnrOf(null) === null);

  const ro = new El(), port = new El(); port.value = "/dev/ttyUSB0";
  const d = new SignalPanel();
  d.$ = (id) => (id === "readout" ? ro : id === "port" ? port : new El());
  Object.assign(d.state, { connected: true, demo: false, rate: 250, rateMeasured: null });
  d.state.quality = { level: "good", alpha_snr: 5.1 };
  d.drawReadout();
  ok("the rate row is labelled DECLARED", ro.innerHTML.includes("<dt>rate (declared)</dt><dd class=\"\">250.0 Hz"), ro.innerHTML);
  ok("...and the measured rate says it is not yet measured", ro.innerHTML.includes("not yet measured"));
  ok("the quality row names a plausibility heuristic, not contact or impedance",
     ro.innerHTML.includes("signal (plausibility heuristic)") && !/impedance<|<dt>contact/.test(ro.innerHTML));
  ok("the alpha SNR is shown with the experimental badge",
     /alpha SNR<\/dt><dd[^>]*>5\.10 <span class="ui-tier sp-beta"/.test(ro.innerHTML), ro.innerHTML);
  d.state.rateMeasured = 249.839; d.state.rateErrorPpm = -644;
  d.state.quality = { level: "marginal", method: "plausibility heuristic" };
  d.drawReadout({ "front end": "reachable" });
  ok("once measured, the measured rate is shown separately with its error",
     ro.innerHTML.includes("<dt>rate (measured)</dt>") && ro.innerHTML.includes("249.839 Hz (-644 ppm)"));
  ok("no alpha row when the bridge sent none", !ro.innerHTML.includes("alpha SNR"));
  d.drawReadout();
  ok("a host's extra readout fields survive the panel's own redraw", ro.innerHTML.includes("front end"));

  const wcol = new El(), wel = new El();
  const wp = new SignalPanel();
  wp.$ = (id) => (id === "widgetcol" ? wcol : id === "widgets" ? wel : new El());
  wp.widgets = wp.widgets;   // remount
  ok("the default widgets are badged experimental", (wel.innerHTML.match(/beta — experimental/g) || []).length === 2);
  wp.widgets = [];
  ok("an empty rack (companion tools absent) hides the Widgets column", wcol.hidden === true && !wel.innerHTML.includes("sp-widget"));
}

for (const f of fail) console.log(`  FAIL ${f}`);
console.log(`[js] ${pass} passed, ${fail.length} failed`);
process.exit(fail.length ? 1 : 0);
