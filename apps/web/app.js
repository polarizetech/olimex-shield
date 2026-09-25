import "./signal-panel/signal-panel.js";
import { Player, fmtTime } from "./playback.js";
/* app.js -- the workbench: Live (the shared panel), Sessions (playback), Electrodes (the guide).
 *
 * The page owns three things and nothing else: which readout is being recorded, the hookup
 * guide that gates Connect, and playback of what was recorded. Device, stream, trace, contact
 * quality, Record and tagging are <signal-panel>'s; every number comes from apps/server.
 *
 * *** THERE IS NO PATH FROM Connect TO THE SERIAL PORT THAT SKIPS THE GUIDE. ***
 * The guide is the panel's `beforeConnect`: fetched first and awaited, and a failed fetch
 * returns false -- it never falls through to connecting. A <dialog>'s `close` event does not
 * fire on a method="dialog" submit in every browser, so the decision is read from `submit`.
 */
const $ = (id) => document.getElementById(id);
const api = (p) => new URL(p.replace(/^\//, ""), document.baseURI).toString();
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const getJSON = (p, init) => fetch(api(p), init).then(async (r) => {
  const j = await r.json().catch(() => ({ error: r.statusText }));
  return r.ok ? j : { ...j, error: j.error || r.statusText };
});
const postJSON = (p, body) => getJSON(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

const S = { readouts: [], gate: null, hookupAt: null, selected: null, storage: null };
const panel = () => $("panel");

function banner(msg) { $("banner").textContent = msg || ""; $("banner").hidden = !msg; }

/* ------------------------------------------------------------------------------ readouts */
async function loadReadouts() {
  const r = await getJSON("api/readouts");
  S.readouts = r.readouts || [];
  $("readout").innerHTML = S.readouts.map((x) => `<option value="${x.key}">${esc(x.label)}</option>`).join("");
  await onReadout();
}

async function onReadout() {
  const key = $("readout").value;
  panel().setAttribute("readout", key);
  // The bridge's contact check is readout-aware: EEG keeps the scalp floor and the experimental
  // alpha ratio; ECG/EMG get rails, mains share and a flat-line floor only. The panel forwards
  // `qualityConfig` as the bridge's `cfg`, and the bridge reads `cfg.readout`.
  panel().qualityConfig = { readout: key };
  const g = await getJSON(`api/gate?readout=${encodeURIComponent(key)}`);
  S.gate = g;
  if (g.error) return banner(g.error);
  const bits = [`<strong>Front end: ${g.overall}</strong> at ${g.probes.feature.f_hz} Hz `
    + `(${g.probes.feature.db.toFixed(1)} dB). ${esc(g.feature_note)}.`];
  if (g.differentiated) bits.push(esc(g.differentiated));
  $("gate").innerHTML = bits.join(" ");
  $("gate").className = "ui-rule banner" + (g.overall === "unreachable" ? " ui-rule--refuted"
    : g.overall === "degraded" ? " ui-rule--spec" : "");
  $("gate").hidden = false;
  if (!$("view-electrodes").hidden) renderGuidePage();
}

/* --------------------------------------------------------------------------------- guide */
function guideHTML(g) {
  const rows = g.checklist.rows.map((r) => `<tr><td><b>${esc(r.role)}</b></td><td>${esc(r.site)}</td>`
    + `<td>${esc(r.where || "")}${r.note ? " — " + esc(r.note) : ""}</td></tr>`).join("");
  return `
    <p class="ui-rule ui-rule--refuted"><b>Safety — the full list, not a summary.</b></p>
    <ul>${g.safety.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    ${g.svg}
    <p><b>${esc(g.checklist.label)}.</b> ${esc(g.checklist.orientation)}</p>
    <table class="hookup-sites"><thead><tr><th>role</th><th>site</th><th>where</th></tr></thead>
      <tbody>${rows}</tbody></table>
    <p class="ui-rule">${esc(g.checklist.schematic_warning || "")}</p>
    ${g.label_collisions.length ? `<p class="ui-rule ui-rule--refuted">${g.label_collisions.length} label(s) overlap on this diagram — read the table, not the picture.</p>` : ""}
    <h3 class="ui-label">Prep, in this order</h3>
    <ol>${g.prep.map((x) => `<li><b>${esc(x.step)}</b> ${esc(x.why)}</li>`).join("")}</ol>
    <h3 class="ui-label">Before you read anything off it</h3>
    <p>Settling window: <b>${g.settling_s} s</b>. ${esc(g.settling_note)}.</p>
    <p>Front end: <b>${esc(g.front_end.overall)}</b>. ${esc(g.front_end.differentiated || "")}</p>
    <h3 class="ui-label">What else makes this same reading</h3>
    <ul>${g.confusables.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <p>On one channel none of these can be told apart from a real response. Controls that would
       separate them: ${g.controls.map(esc).join("; ")}.</p>`;
}

async function fetchGuide() {
  return getJSON(`api/hookup?readout=${encodeURIComponent($("readout").value)}`)
    .catch((e) => ({ error: String(e) }));
}

async function renderGuidePage() {
  const g = await fetchGuide();
  $("guide").className = "guide";
  $("guide").innerHTML = g.error ? `<p class="ui-rule ui-rule--refuted">${esc(g.error)}</p>`
    : `<h2 class="ui-display--3">${esc(g.label)} — where the electrodes go</h2>${guideHTML(g)}`;
}

function askHookup() {
  return new Promise((resolve) => {
    const dlg = $("hookup"), form = dlg.querySelector("form");
    const once = (ev) => { form.removeEventListener("submit", once); resolve((ev.submitter && ev.submitter.value) === "go"); };
    form.addEventListener("submit", once);
    dlg.showModal();
  });
}

async function hookupGate() {
  banner("");
  const g = await fetchGuide();
  if (g.error) {
    banner(`Could not load the hookup guide (${g.error}), so nothing was connected. The guide carries the safety list and is not optional.`);
    return false;
  }
  $("hookup-title").textContent = `${g.label} — where the electrodes go`;
  $("hookup-body").innerHTML = guideHTML(g);
  const go = await askHookup();
  if (go) S.hookupAt = Math.floor(Date.now() / 1000);
  return go;
}

/** What the panel adds to a session when Record starts. `electrodes_on_at` is when the operator
 *  confirmed the electrodes were on -- not "now", which would assert zero settling. */
function sessionMeta() {
  const key = $("readout").value;
  const r = S.readouts.find((x) => x.key === key) || {};
  return { project: "olimex-shield", readout: key, front_end: S.gate ? S.gate.overall : null,
           montage: r.montage || [], site: (r.site_examples || [])[0] || "",
           ...(S.hookupAt ? { electrodes_on_at: S.hookupAt } : {}) };
}

function wirePanel() {
  const p = panel();
  p.beforeConnect = hookupGate;
  p.sessionMeta = sessionMeta;
  p.addEventListener("signal-recorded", async (e) => {
    const stamp = e.detail.stamp;
    if (!stamp) return;
    // The bridge's measured rate needs ~30 s, so it is added once the session is finished.
    // What the wire lost while the black box was armed comes back from the bridge's /record/stop
    // (recParseErrors / recGaps / recMaxGapUs), counted from the board's t_us -- never repaired.
    const ri = p.rateInfo || {};
    const d = e.detail || {};
    const note = { stamp };
    if (ri.measured) {
      Object.assign(note, { rate_measured_hz: ri.measured, rate_error_ppm: ri.errorPpm,
        rate_uncertainty_ppm: ri.uncertaintyPpm, rate_basis: ri.basis, hookup_confirmed_at: S.hookupAt });
    }
    if (d.recGaps != null || d.recParseErrors != null) {
      Object.assign(note, { stream_parse_errors: d.recParseErrors ?? null, stream_gaps: d.recGaps ?? null,
        stream_max_gap_us: d.recMaxGapUs ?? null,
        stream_integrity_basis: "bridge black box, board t_us; gap = step > 1.5 x declared period" });
    }
    if (Object.keys(note).length > 1) await postJSON("dataset/annotate", note);
    banner("");
    await loadSessions(stamp);
    notice(`Recorded ${stamp}. It is in Sessions.`);
  });
}

function notice(msg) {
  const el = $("banner");
  el.className = "ui-rule ui-rule--measured banner";
  el.textContent = msg; el.hidden = false;
  setTimeout(() => { el.className = "ui-rule ui-rule--refuted banner"; if (el.textContent === msg) el.hidden = true; }, 8000);
}

/* ------------------------------------------------------------------------------ sessions */
const player = new Player({ overview: $("pl-overview"), trace: $("pl-trace"), clock: $("pl-clock"),
  play: $("pl-play"), prev: $("pl-prev"), next: $("pl-next"), speed: $("pl-speed"),
  window: $("pl-window"), tags: $("pl-tags") });

async function loadSessions(select) {
  const [list, st] = await Promise.all([getJSON("api/sessions"), getJSON("api/storage")]);
  S.storage = st;
  $("store").textContent = `stored in ${list.store || "?"} · uploads: ${st.uploader}${st.ready ? "" : " (not ready)"}`;
  const rows = (list.sessions || []).map((s) => `<tr data-stamp="${esc(s.stamp)}">
      <td class="ui-mono">${esc(s.stamp)}</td><td>${esc(s.readout)}</td>
      <td>${s.source === "synthetic" ? "<b>SYNTHETIC</b>" : esc(s.source)}${s.open ? " (recording)" : ""}</td>
      <td class="num">${s.n_samples && s.rate_hz ? fmtTime(s.n_samples / s.rate_hz) : "—"}</td>
      <td class="num">${s.n_tags}</td><td class="num">${s.uploads || 0}</td></tr>`).join("");
  $("session-list").querySelector("tbody").innerHTML = rows
    || `<tr><td colspan="6">No sessions yet. Record one from Live.</td></tr>`;
  for (const tr of $("session-list").querySelectorAll("tr[data-stamp]")) {
    tr.onclick = () => openSession(tr.dataset.stamp);
  }
  if (select) openSession(select);
}

async function openSession(stamp) {
  S.selected = stamp;
  for (const tr of $("session-list").querySelectorAll("tr[data-stamp]")) {
    tr.setAttribute("aria-selected", tr.dataset.stamp === stamp ? "true" : "false");
  }
  const s = await getJSON(`api/session?id=${encodeURIComponent(stamp)}&seconds=86400`);
  if (s.error) { $("pl-result").textContent = s.error; return; }
  const m = s.meta || {};
  $("player").hidden = false;
  $("pl-title").textContent = stamp;
  $("pl-tier").setAttribute("tier", m.source === "synthetic" ? "SPEC" : "MEASURED");
  const warn = [m.synthetic_warning, m.tag_clock_warning].filter(Boolean).join(" ");
  $("pl-warn").textContent = warn; $("pl-warn").hidden = !warn;
  const rows = [
    ["readout", m.readout], ["source", m.source], ["samples", m.n_samples],
    ["declared rate", `${m.rate_hz} Hz`],
    ["measured rate", m.rate_measured_hz ? `${m.rate_measured_hz} Hz (${m.rate_error_ppm} ppm)` : "not recorded"],
    ["wall-clock rate", m.effective_rate_hz ? `${(+m.effective_rate_hz).toFixed(2)} Hz` : "—"],
    ["stream", m.stream_gaps != null ? `${m.stream_gaps} gap(s), ${m.stream_parse_errors ?? 0} malformed line(s)` : "not recorded"],
    ["front end", m.front_end], ["montage", (m.montage || []).map((x) => `${x.role}: ${x.site}`).join(" · ")],
  ];
  $("pl-meta").innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v ?? "—")}</dd>`).join("");
  $("pl-tags").innerHTML = (s.tags || []).map((t) => `<li data-t="${t.t_s}">${fmtTime(t.t_s)} — ${esc(t.label)}</li>`).join("");
  for (const li of $("pl-tags").children) li.onclick = () => player.seek(+li.dataset.t - 0.5);
  $("pl-upload").disabled = !(S.storage && S.storage.ready) || m.stopped_at == null;
  $("pl-upload").title = S.storage && !S.storage.ready ? S.storage.reason : "";
  $("pl-result").textContent = "";
  player.load(s);
}

async function upload() {
  $("pl-result").textContent = "uploading…";
  const r = await postJSON("api/upload", { stamp: S.selected });
  $("pl-result").textContent = r.error ? `Upload failed: ${r.error}` : `Uploaded ${r.files ?? ""} file(s) → ${r.target || r.uploader}`;
  loadSessions();
}

async function exportBids() {
  $("pl-result").textContent = "exporting…";
  const r = await postJSON("api/export/bids", { stamp: S.selected, subject: $("pl-sub").value, task: $("pl-task").value });
  $("pl-result").textContent = r.error ? `Not exported: ${r.error}` : `BIDS written: ${r.header}\n${r.n_samples} samples, ${r.events} events, scaling: ${r.scaling}`;
}

/* ---------------------------------------------------------------------------------- tabs */
function show(view) {
  for (const b of $("tabs").querySelectorAll("button")) b.setAttribute("aria-selected", b.dataset.view === view ? "true" : "false");
  for (const sec of document.querySelectorAll("main > section[data-view]")) sec.hidden = sec.dataset.view !== view;
  if (view === "sessions") loadSessions(S.selected);
  if (view === "electrodes") renderGuidePage();
  try { history.replaceState(null, "", `#${view}`); } catch { /* sandboxed */ }
}

/* -------------------------------------------------------------------------------- wiring */
$("readout").onchange = onReadout;
$("refresh").onclick = () => loadSessions(S.selected);
$("pl-upload").onclick = upload;
$("pl-bids").onclick = exportBids;
for (const b of $("tabs").querySelectorAll("button")) b.onclick = () => show(b.dataset.view);

wirePanel();
// The Atlas tab and the extraction widgets come from optional companion analysis tools. Offer them
// only when they are actually there; a tab that 404s on click is worse than no tab.
getJSON("api/tools").then((t) => {
  S.tools = t;
  if (t.atlas) panel().setAttribute("atlas", "");
  if (!t.detection) panel().widgets = [];
}).catch(() => {});
loadReadouts().then(() => show((location.hash || "#live").slice(1) || "live"));

export { S, player };
