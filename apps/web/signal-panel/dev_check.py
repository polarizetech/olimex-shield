#!/usr/bin/env python3
"""dev_check.py -- signal-panel's gate. `python3 apps/web/signal-panel/dev_check.py`

Static assertions over the component, because the thing it must not do -- open a port
without the host's gate having run -- is exactly the bug that is invisible when it happens.
Skips the JS behaviour suite LOUDLY without node.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
JS = (HERE / "signal-panel.js").read_text()
CSS = (HERE / "signal-panel.css").read_text()
# Strip comments before asserting on code. Three checks in an earlier project matched their own
# explanatory comments; the repair is to look at the code, not to weaken the check.
CODE = re.sub(r"/\*[\s\S]*?\*/", "", JS)
CODE = re.sub(r"(^|[^:])//.*$", r"\1", CODE, flags=re.M)
CSSC = re.sub(r"/\*[\s\S]*?\*/", "", CSS)

P, F, S = [], [], []


def ok(n, c, note=""):
    (P if c else F).append(f"{n}{(' -- ' + note) if note else ''}")


# --- the consent gate: there must be no path from Connect to /open that skips beforeConnect
body = CODE[CODE.index("async toggleConnect()") : CODE.index("async disconnect()")]
gate, open_at = body.find("beforeConnect"), body.find("'open'")
ok("toggleConnect consults beforeConnect BEFORE it opens a port", 0 <= gate < open_at)
ok(
    "and it AWAITS it -- a promise that is not awaited is not a gate",
    re.search(r"await this\.beforeConnect\(", body) is not None,
)
ok(
    "a false return aborts rather than falling through",
    re.search(r"if \(!go\) return", body) is not None,
)
ok("a throw in the host's gate aborts too", "catch (e) { return this.fail" in body)

# --- the tier: from the bridge's status, never from the port's name
ok(
    "the demo tier is read from status.demo",
    re.search(r"s\.demo\s*=\s*!!st\.demo", CODE) is not None,
)
ok(
    "and never inferred from the port string",
    not re.search(r"demo\s*=.*port", CODE) and not re.search(r"port.*startsWith\(.demo", CODE),
)
ok("a synthetic source is badged MODELLED", "'MODELLED' : 'MEASURED'" in CODE)

# --- it must not own the device or reimplement the bridge
ok("it opens no serial port itself -- no Web Serial anywhere", "navigator.serial" not in CODE)
ok(
    "every request goes through the host's own bridge proxy",
    not re.search(r"https?://(localhost|127\.0\.0\.1):8140", CODE),
)
ok(
    "contact quality is the bridge's own /quality, not a local reimplementation",
    "'quality'" in CODE and "bandPower" not in CODE and "goertzel" not in CODE.lower(),
)
ROUTES = set(re.findall(r"_url\('([a-z/-]+)'\)", CODE)) | set(
    re.findall(r"_post\('([a-z/-]+)'", CODE)
)
ok(
    "every bridge route it calls is one the bridge actually has",
    {
        "ports",
        "open",
        "close",
        "status",
        "stream",
        "quality",
        "record",
        "record/stop",
        "spectrum",
        "bands",
        "integration-check",
        "extract",
    }
    >= ROUTES,
    f"{sorted(ROUTES)}",
)
ok("it opens the port with /open, never /connect", "open" in ROUTES and "connect" not in ROUTES)

# --- what the host gets back. A panel the project cannot read from is decoration.
for ev in ("signal-samples", "signal-recorded", "signal-connected", "signal-quality"):
    ok(f"emits {ev}", f"'{ev}'" in CODE)
ok("exposes recent(n) so a project can pull the live signal at any time", "recent(n)" in CODE)
ok("the ring is read from head-filled, not from 0", "s.head - len + s.ring.length" in CODE)

# --- drawing
ok(
    "drawing is setInterval, not requestAnimationFrame",
    "setInterval" in CODE and "requestAnimationFrame" not in CODE,
)
ok(
    "the trace states its own axes rather than autoscaling silently",
    "/div" in CODE and "s/div" in CODE,
)
ok("a stale readout is dimmed, not removed", "is-idle" in CODE)

# --- 2026-09-14: merged from the bridge's former built-in scope page, prioritised as the
# implementation per the operator's direction -- so these checks pin the merge, not just the
# fact that some code exists.
ok(
    "the quality gate is fed the configured µV/count and mains, not a hardcoded default",
    "uv_per_count: +this.$('uvpc').value" in CODE and "mains_hz: +this.$('mains').value" in CODE,
)
ok(
    "the display filter is declared cosmetic and stated on the panel, never fed to a readout",
    "cosmetic" in CODE and "NEVER feeds a number" in JS,
)
body_check = CODE[CODE.index("async checkQuality(cfg") : CODE.index("async _refreshAnalysis()")]
ok(
    "checkQuality never reads a readout back into itself -- "
    "readouts come from the gate, not vice versa",
    "drawReadout" not in body_check,
)
ok(
    "spectrum and bands are drawn from the bridge's own numbers, not recomputed here",
    "drawSpectrum()" in CODE
    and "drawBands()" in CODE
    and "goertzel" not in CODE.lower()
    and "fft" not in CODE.lower(),
)
ok(
    "the widget rack is HOST-extensible: a host adds a panel by pushing an object",
    "this.widgets = defaultWidgets()" in CODE,
)
WIDGET_IDS = set(re.findall(r"id: '([a-z]+)', title:", CODE))
ok(
    "both of scope.js's default widgets came across",
    {"integration", "lockin"} == WIDGET_IDS,
    f"{WIDGET_IDS}",
)
ok(
    "a widget that needs more buffer than exists says so instead of returning nonsense",
    "needs ${w.needs} s of buffer" in CODE,
)
ok(
    "one widget pass at a time -- these are O(n) server-side calls",
    "_widgetBusy" in CODE and "finally { this._widgetBusy = false; }" in CODE,
)
ok(
    "the Atlas panel is an OPTIONAL tab, hidden unless the host asks for it",
    "hasAttribute('atlas')" in CODE and "tabs.hidden = !hasAtlas" in CODE,
)
ok(
    "the Atlas panel is dynamically imported -- a host that never uses it pays nothing",
    re.search(r"await import\(new URL\('\./atlas-panel\.js'", CODE) is not None,
)
ok(
    "mounting the atlas panel passes this panel's OWN bridge attribute through, not a copy",
    "this._atlasEl.setAttribute('bridge', this.bridge)" in CODE,
)
# REGRESSION: the design system's `.ui-tabs { display: flex }` and the browser's own
# `[hidden] { display: none }` tie on specificity, and the author rule wins -- found by
# opening a host page in a browser and seeing the tab bar despite no `atlas` attribute.
ok(
    "REGRESSION: [hidden] actually hides the tab bar, despite .ui-tabs's own display:flex",
    "signal-panel [hidden]" in CSSC and "display: none !important" in CSSC,
)

# --- found rewiring an earlier client (2026-09-14): four things the panel had wrong or lacked
ok(
    "REGRESSION: the rate is read from the bridge's `rate` key, never the nonexistent `rate_hz`",
    "r.rate || st.rate" in CODE and "rate_hz" not in CODE.replace("rate_hz: s.rate", ""),
)
qbody = CODE[CODE.index("async checkQuality(cfg") : CODE.index("async _refreshAnalysis()")]
ok(
    "REGRESSION: /quality is sent `rate`, which is the key the bridge reads",
    "samples, rate: s.rate" in qbody and "rate_hz" not in qbody,
)
ok(
    "a DOWN bridge (a JSON error from the host proxy) is reported, not silently ignored",
    re.search(r"if \(r\.error\) this\.fail", CODE) is not None,
)
ok(
    "the stream is opened 2 s back from the bridge total, "
    "never replaying a whole already-open ring",
    "st.total" in CODE and "openStream(from = 0)" in CODE,
)
ok(
    "stream gaps are counted from `from`, not concatenated across",
    "d.from > expect" in CODE and "s.gaps += gap" in CODE,
)
ok(
    "widgets (lock-in work) get the bridge's MEASURED rate when it exists, and are told which",
    "rate: this.analysisRate, rateMeasured: s.rateMeasured" in CODE
    and "DECLARED — not yet measured" in CODE,
)
ok(
    "a new connection never carries a previous port's measured rate",
    "s.rateMeasured = st.rateMeasured ?? null" in CODE,
)
ok(
    "view=controls hides the panel's own trace/readout/analysis/record",
    "for (const id of ['record', 'scope', 'readout', 'analysis'])" in CODE,
)
ok("...and asks the bridge for nothing it will not draw", "if (this.controlsOnly) return;" in CODE)

# --- the design system owns every colour and font
lits = re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", CSSC)
ok("signal-panel.css carries no colour literal", not lits, f"{lits}")
ok(
    "no font-family literal",
    not [m for m in re.findall(r"font-family:\s*([^;]+);", CSSC) if "var(" not in m],
)
ok(
    "no font-size literal",
    not [m for m in re.findall(r"font-size:\s*([^;]+);", CSSC) if "var(" not in m],
)
ok(
    "colours in the JS come from design tokens",
    all(t in CODE for t in ("--series-measured", "--border"))
    and "#" not in "".join(re.findall(r"css\('([^']+)'", CODE)),
)

# --- tagging: the rules that used to live in one project's sessions.py, now shared
ok(
    "the tag clock is the sample counter, never the wall clock",
    re.search(r"const t_s = s\.rate \? \(s\.total - s\.recordStart\) / s\.rate", CODE) is not None
    and not re.search(r"t_s[^\n]*Date\.now", CODE),
)
ok(
    "and it is zeroed at RECORD, not at connect -- the dataset indexes from record",
    "s.recordStart = s.total" in CODE,
)
ok(
    "a tag is refused unless a recording is running",
    re.search(r"if \(!s\.recording\) return null", CODE) is not None,
)
ok("an empty label is refused", "if (!label) return null" in CODE)
ok(
    "tags reach the shared dataset, not a per-project store",
    "'dataset/tag'" in CODE and "'dataset/start'" in CODE and "'dataset/stop'" in CODE,
)
ok(
    "samples are batched to the dataset rather than one POST per sample",
    "_store(" in CODE and "Math.max(64" in CODE,
)
ok(
    "a failed batch is put BACK -- a dropped batch is a hole nothing downstream can see",
    "this._pending = batch.concat" in CODE,
)
ok(
    "recording opens BOTH artefacts: the bridge's black box and a dataset session",
    "'record'" in CODE and "black_box" in CODE,
)
ok(
    "keys 1-9 fire quick tags, and not while typing in a field",
    "'123456789'.indexOf" in CODE and "t === 'INPUT'" in CODE,
)
ok("the key handler is removed when the element goes away", "removeEventListener('keydown'" in CODE)
ok(
    "the tag bar is hidden until a recording is running",
    re.search(r"\$\('tagbar'\)\.hidden = false", CODE) is not None
    and re.search(r"\$\('tagbar'\)\.hidden = true", CODE) is not None,
)
ok("emits signal-tag so the host can act on a tag as it happens", "'signal-tag'" in CODE)
ok(
    "the tag timeline is its own canvas, not redrawn into the trace",
    'data-el="timeline"' in JS and "drawTimeline()" in CODE,
)
ok(
    "the tag input is styled as a field, not left bare",
    ".sp-tagfield" in CSSC and ":focus-within" in CSSC,
)

# --- the experimental silo: badged, still usable, and honest about what the numbers are
ok(
    "the experimental badge uses the design system's tier badge, with the docs pointer",
    'class="ui-tier sp-beta" data-family="exploring"' in CODE
    and "beta — experimental" in CODE
    and "Not an established method for this hardware; see docs/experimental.md" in CODE,
)
ok(
    "both default widgets are flagged experimental and the rack badges flagged widgets",
    CODE.count("experimental: true,") >= 2 and "w.experimental ? ' ' + betaBadge()" in CODE,
)
ok(
    "the Atlas tab carries the badge, on the tab and above the panel",
    "Atlas ${betaBadge()}" in CODE and "ui-rule--exploring sp-beta-note" in CODE,
)
ok(
    "the lock-in amplitude is labelled uncalibrated",
    "amplitude (uncalibrated)" in CODE and "not calibrated" in CODE,
)
ok(
    "an experimental response's own note is shown when the bridge sends one",
    "serverNote(r)" in CODE,
)
ok(
    "the readout labels the rate DECLARED and shows the measured one separately",
    "'rate (declared)'" in CODE and "'rate (measured)'" in CODE,
)
ok(
    "the quality row says it is a plausibility heuristic, not impedance or 'contact'",
    "plausibility heuristic" in CODE and "['contact'," not in CODE,
)
ok(
    "the alpha-SNR part is badged when it is shown",
    "['alpha SNR', `${alpha.toFixed(2)} ${betaBadge()}`" in CODE,
)
ok(
    "replacing the widget rack remounts it (hidden when companion tools are absent)",
    "set widgets(v)" in CODE and "col.hidden = !this.widgets.length" in CODE,
)
ok(
    "the panel draws its own readout on the frame loop",
    "this.drawTimeline(); this.drawReadout();" in CODE,
)

node = shutil.which("node")
if node:
    r = subprocess.run([node, str(HERE / "dev_check_js.mjs")], capture_output=True, text=True)
    print(r.stdout.strip())
    m = re.search(r"\[js\] (\d+) passed, (\d+) failed", r.stdout)
    if m:
        P.extend(["js"] * int(m.group(1)))
        F.extend(["js check"] * int(m.group(2)))
    else:
        F.append(f"dev_check_js.mjs gave no summary: {r.stderr[-200:]}")
else:
    S.append("dev_check_js.mjs -- node absent; the behaviour checks did NOT run")

for s in S:
    print(f"  SKIP {s}")
for f in F:
    print(f"  FAIL {f}")
print(
    f"\nsignal-panel/dev_check: {len(P)}/{len(P) + len(F)} passed"
    + (f", {len(S)} skipped" if S else "")
)
sys.exit(1 if F else 0)
