#!/usr/bin/env python3
"""
dev_check.py — self-tests for the olimex-shield bridge (apps/server).

The Auditory Response Atlas and the extraction layer live in optional companion analysis tools
(auditory-atlas, signal-detection), and their tests live with them. What is tested here is what
this board owns: the daemon, its contact check, its rate measurement, its durability contract,
its constants -- and that the optional tools switch off cleanly when absent.

Run: python3 apps/server/dev_check.py
Stdlib only. No network, no device.
"""

import ast
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PASS = FAIL = 0
FAILURES = []
FS = 250.0


def ok(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")


def section(name):
    print(f"\n\033[1m{name}\033[0m")


# ============================================================ service ==============
section("1. Service — optional tools must not be able to break acquisition")

serve_src = (HERE / "serve.py").read_text()
ok(
    "the atlas and detection imports are guarded",
    "_HAVE_ATLAS" in serve_src and "_HAVE_DETECTION" in serve_src,
)
ok("...with a stand-in so an error handler cannot itself NameError", "class _Missing" in serve_src)
ok("a firewall error is a 400, not a 500", "_FIREWALL_ERRORS" in serve_src and "400" in serve_src)
ok("static files are served by allow-list, never a directory mount", "STATIC = {" in serve_src)
ok(
    "CORS stays on for local apps on other ports, but is an allow-list, never `*`",
    "Access-Control-Allow-Origin" in serve_src
    and '"Access-Control-Allow-Origin", "*"' not in serve_src
    and "OLIMEX_ALLOWED_ORIGINS" in serve_src,
)
ok(
    "recordings stay gitignored",
    "recordings/" in (HERE.parents[1] / ".gitignore").read_text().split(),
)
daemon_src = serve_src.split("class SerialDaemon", 1)[1].split("DAEMON = SerialDaemon", 1)[0]
ok(
    "the serial daemon carries no dependency on any analysis tool",
    not any(
        w in daemon_src for w in ("auditory.", "montage.", "forward.", "extract.", "noise_budget.")
    ),
)
for gone in ("auditory", "electrodes", "forward", "montage", "claims", "extract", "noise_budget"):
    ok(
        f"{gone}.py does not live in this repo (it belongs to an optional tool)",
        not (HERE / f"{gone}.py").exists(),
        gone,
    )
ok("bioacq/ does not live in this repo (it is a separate tool)", not (HERE / "bioacq").exists())

# The switch-off, exercised in a clean interpreter with the tools deliberately unreachable.
_probe = subprocess.run(
    [
        sys.executable,
        "-c",
        "import json, serve; print(json.dumps([serve._HAVE_ATLAS, serve._HAVE_DETECTION, "
        "serve._missing('x', 'y')['hint'], serve._missing('x', 'y')['experimental'], "
        "serve.experimental.handle_get('/claims')[0], "
        "serve.experimental.handle_post('/extract', {}, samples_for=None, rate_for=None)[1]]))",
    ],
    cwd=HERE,
    capture_output=True,
    text=True,
    env={**os.environ, "OLIMEX_TOOLS": "/nonexistent"},
)
_flags = json.loads(_probe.stdout.strip().splitlines()[-1]) if _probe.returncode == 0 else None
ok(
    "with no tools present the bridge still imports, and both halves report absent",
    _flags is not None and _flags[0] is False and _flags[1] is False,
    _probe.stderr[-200:],
)
ok(
    "...and a missing tool's 503 says where the routes come from",
    _flags is not None and "auditory-atlas" in _flags[2],
)
ok(
    "...and is itself marked experimental, GET and POST alike",
    _flags is not None
    and _flags[3] is True
    and _flags[4] == 503
    and _flags[5]["experimental"] is True
    and "docs/experimental.md" in _flags[5]["note"],
)

import quality  # noqa: E402
import rig  # noqa: E402

ok(
    "the contact check does not import any optional tool",
    not re.search(
        r"^\s*(import|from)\s+(extract|noise_budget)\b", (HERE / "quality.py").read_text(), re.M
    ),
)
import experimental  # noqa: E402
import serve  # noqa: E402

if serve._HAVE_DETECTION:
    _x = [math.sin(2 * math.pi * 10 * k / FS) + 0.1 * math.cos(k) for k in range(500)]
    ok(
        "quality's Goertzel copy is identical to signal-detection's",
        all(
            quality._goertzel_power(_x, FS, b, 500)
            == experimental.extract._goertzel_power(_x, FS, b, 500)
            for b in (3, 20, 40, 97)
        ),
    )
    ok(
        "with the tools present, /claims merges both registers",
        experimental.all_claims()["counts"]["evidence"]
        == len(experimental.atlas_claims.EVIDENCE) + len(experimental.detection_claims.EVIDENCE),
    )
    _code, _body = experimental.handle_get("/claims")
    ok(
        "...and every experimental response says it is experimental",
        _code == 200 and _body["experimental"] is True and _body["note"],
    )
else:
    print("  SKIP Goertzel parity and merged claims -- signal-detection tool not reachable")

# ============================================================ rig constants ========
section("2. This board's constants")
ok(
    "the recalled rig figures are marked not corpus-eligible and carry a how-to-verify",
    experimental.RECALLED["corpus_eligible"] is False
    and "datasheet" in experimental.RECALLED["how_to_verify"].lower(),
)
ok(
    "the measured rig figures are corpus-eligible, unlike the recalled ones",
    experimental.MEASURED_RIG["corpus_eligible"] is True,
)
ok(
    "the nV rig figures and the RECALLED table live in experimental.py, labelled so",
    not any(hasattr(rig, k) for k in ("MEASURED_RIG", "RECALLED", "NOISE_NV_AT_40HZ"))
    and all(
        d.get("experimental") is True
        for d in (experimental.MEASURED_RIG, experimental.RECALLED, experimental.NOISE_NV_AT_40HZ)
    ),
)
_rig_src = (HERE / "rig.py").read_text()
ok(
    "µV/count provenance: the built-in cal signal at nominal amplitude, not externally verified",
    "built-in cal" in rig.UV_PER_COUNT_PROVENANCE
    and "not externally verified" in rig.UV_PER_COUNT_PROVENANCE
    and "nominal" in rig.UV_PER_COUNT_PROVENANCE,
)
ok(
    "...and rig.py no longer claims the circular 'independently recovered' audit",
    "independently recovered" not in _rig_src and "audit_rig" not in _rig_src,
)
ok(
    "...and the scale's value is unchanged (7.9)",
    rig.UV_PER_COUNT == 7.9 and rig.UV_PER_COUNT_DATASHEET == 1.72,
)
_rig_imports = set()
for _n in ast.walk(ast.parse(_rig_src)):
    if isinstance(_n, ast.Import):
        _rig_imports |= {a.name for a in _n.names}
    elif isinstance(_n, ast.ImportFrom):
        _rig_imports.add(_n.module)
ok("rig.py imports only the stdlib", _rig_imports <= {"math", "os"}, str(_rig_imports))
_saved_mains = os.environ.pop("OLIMEX_MAINS_HZ", None)
ok(
    "with $OLIMEX_MAINS_HZ unset, no mains frequency is configured",
    rig.configured_mains_hz() is None,
)
os.environ["OLIMEX_MAINS_HZ"] = "50"
ok("...and $OLIMEX_MAINS_HZ sets it", rig.configured_mains_hz() == 50.0)
os.environ["OLIMEX_MAINS_HZ"] = "fifty"
ok("...and a non-number is ignored rather than guessed", rig.configured_mains_hz() is None)
os.environ.pop("OLIMEX_MAINS_HZ")
if _saved_mains is not None:
    os.environ["OLIMEX_MAINS_HZ"] = _saved_mains
# CORRECTED 2026-09-13: this check used to REQUIRE the note to say electrode preparation dominates.
# The sidecars contradict that (the good-contact capture has the highest 40 Hz figure), so the
# check now requires the record to say the spread is NOT instrument noise and is unattributed.
ok(
    "...and the measured record does not attribute the spread to electrode prep without evidence",
    "not instrument noise" in experimental.MEASURED_RIG["note"]
    and "Electrode preparation dominates" not in experimental.MEASURED_RIG["note"],
)
ok(
    "...and the median is a true median of the six captures, not the upper-middle value",
    abs(experimental.MEASURED_RIG["in_band_noise_nv_at_40hz_60s"] - 156.7) < 0.5,
)
ok(
    "the two µV/count figures agree with the constant",
    experimental.MEASURED_RIG["uv_per_count"] == rig.UV_PER_COUNT,
)
_rnf = (HERE / "validation" / "rig_noise_floor.py").read_text()
ok(
    "the rig noise-floor script exists and reads the private captures without writing anything",
    "PRIVATE DATA" in _rnf,
)
ok(
    "...finds them ONLY through $OLIMEX_RIG_CAPTURES, never by walking into another project",
    "OLIMEX_RIG_CAPTURES" in _rnf and '"projects"' not in _rnf,
)
ok(
    "the rig's own validation write-up stays with the rig",
    "the gate, run against this rig" in (HERE / "validation" / "VALIDATION.md").read_text(),
)

# ============================================================ 12b. session UI ======
_SIGNAL_PANEL = HERE.parent / "web" / "signal-panel"
section("3. The contact check — the quality gate the panel runs on")

import quality  # noqa: E402

# The pre-flight gate, ported from an earlier internal project so every client gets the same
# answer.
_qr = random.Random(11)
good_ch = [
    512 + 30 * math.sin(2 * math.pi * 10 * k / FS) + _qr.gauss(0, 20) for k in range(int(FS * 20))
]
flat_ch = [512 + _qr.gauss(0, 0.4) for _ in range(int(FS * 20))]
railed = [1023 if k % 2 else 0 for k in range(int(FS * 20))]
qg = quality.assess(good_ch, FS, uv_per_count=7.9)
ok("a channel with alpha and sane amplitude reads good", qg["level"] == "good", qg["level"])
qf = quality.assess(flat_ch, FS, uv_per_count=7.9)
ok(
    "a channel at the converter's floor reads UNUSABLE, not merely quiet",
    qf["level"] == "unusable" and any("flat/implausible" in r for r in qf["reasons"]),
)
_all_text = json.dumps([qf, quality.assess(railed, FS, uv_per_count=7.9), qg])
ok(
    "no message claims an impedance or scalp-contact MEASUREMENT -- it measures plausibility",
    "impedance" not in " ".join(qf["reasons"]).lower()
    and "no scalp contact" not in _all_text.lower()
    and "high impedance" not in _all_text.lower(),
)
ok(
    "the verdict names its method, and flags the alpha ratio as experimental",
    qg["method"] == "plausibility heuristic"
    and qg["alpha_snr_detail"]["experimental"] is True
    and qg["alpha_snr_detail"]["applied"] is True
    and qg["alpha_snr"] == qg["alpha_snr_detail"]["value"],
)
ok(
    "the response keys the panel reads are all still there",
    {"ready", "level", "amplitude_uv", "alpha_snr", "mains_rel", "railing_frac", "reasons"}
    <= set(qg)
    and {"checklist", "thresholds", "mains_hz", "seconds", "note"} <= set(qg),
)
# READOUT-AWARE. A limb lead has no alpha and need not clear a scalp-EEG amplitude floor. A small
# but plausible non-EEG signal (sd ~4 counts, no alpha, little mains) must pass for ECG/EMG while
# the same samples fail the EEG floor.
_small = [512 + 4 * math.sin(2 * math.pi * 1.2 * k / FS) + _qr.gauss(0, 2) for k in range(5000)]
_qe = quality.assess(_small, FS, uv_per_count=7.9, readout="eeg")
_qc = quality.assess(_small, FS, uv_per_count=7.9, readout="ecg")
_qm = quality.assess(_small, FS, uv_per_count=7.9, readout="emg")
ok("EEG applies the scalp amplitude floor to a small signal", _qe["level"] == "unusable")
ok(
    "ECG and EMG are NOT judged on alpha or the scalp floor",
    _qc["ready"] and _qm["ready"] and _qc["alpha_snr"] is None and _qm["alpha_snr"] is None,
    json.dumps(_qc["reasons"]),
)
ok(
    "...their alpha sub-result says it was not applied",
    _qc["alpha_snr_detail"]["applied"] is False and _qc["alpha_snr_detail"]["experimental"],
)
ok(
    "...but a flat ECG channel is still refused",
    quality.assess(flat_ch, FS, uv_per_count=7.9, readout="ecg")["level"] == "unusable",
)
ok(
    "...and so is a railing one",
    quality.assess(railed, FS, uv_per_count=7.9, readout="emg")["level"] == "unusable",
)
_mainsy = [512 + 30 * math.sin(2 * math.pi * 60 * k / FS) + _qr.gauss(0, 2) for k in range(5000)]
ok(
    "...and so is one dominated by mains",
    any("mains" in r for r in quality.assess(_mainsy, FS, readout="ecg", mains_hz=60)["reasons"]),
)
ok(
    "an unknown readout gets the conservative physiology-free checks, not EEG's",
    quality.assess(_small, FS, uv_per_count=7.9, readout="plant")["alpha_snr"] is None,
)
os.environ["OLIMEX_MAINS_HZ"] = "50"
_q50 = quality.assess(good_ch, FS)
os.environ.pop("OLIMEX_MAINS_HZ")
ok(
    "with no caller value the check takes $OLIMEX_MAINS_HZ, and says where it came from",
    _q50["mains_hz"] == 50.0 and _q50["mains_hz_basis"] == "OLIMEX_MAINS_HZ",
)
ok(
    "...and falls back to the bench default only with a label saying so",
    "bench default" in quality.assess(good_ch, FS)["mains_hz_basis"],
)
# HANN + HALF-OPEN BANDS. A pure 13 Hz tone sat on the shared 13 Hz edge and was counted in both
# alpha and beta; bands are now [lo, hi), so it is beta only, and the bands partition 1-45 Hz.
_t13 = [math.sin(2 * math.pi * 13.0 * k / FS) for k in range(1000)]
_b13 = quality.bands(_t13, FS)
ok(
    "a tone on a band edge is counted once: its bin is beta's, alpha sees only Hann leakage",
    _b13["beta"] > 0.8 and _b13["alpha"] < 0.2 and abs(_b13["alpha"] + _b13["beta"] - 1) < 1e-6,
    f"alpha {_b13['alpha']:.3f} beta {_b13['beta']:.3f}",
)
ok(
    "the five bands partition 1-45 Hz exactly",
    abs(sum(v for k, v in _b13.items() if not k.startswith("_")) - 1.0) < 1e-9,
)
_sp = quality.spectrum([100.0 * math.sin(2 * math.pi * 10 * k / FS) for k in range(1000)], FS)
ok(
    "the Hann-windowed spectrum still reads a sinusoid's amplitude correctly",
    abs(max(_sp["amps"]) - 100.0) < 1.0 and _sp["window"] == "hann",
)
ok("...and hands back a checklist of what to physically fix", len(qf["checklist"]) >= 3)
qr_ = quality.assess(railed, FS, uv_per_count=7.9)
ok("a railing channel is caught by the rail check", qr_["railing_frac"] > 0.9)
ok(
    "under a second of data returns no_signal rather than a confident verdict",
    quality.assess([512.0] * 10, FS)["level"] == "no_signal",
)
ok(
    "the verdict says it gates CONTACT, not whether the session will find anything",
    "says nothing about what the session" in qg["note"],
)
ok(
    "mains frequency is a parameter, not a constant — this rig is 60 Hz, ds005185 was 50",
    quality.assess(good_ch, FS, mains_hz=50.0)["mains_hz"] == 50.0,
)
ok(
    "uV and raw counts are distinguished, so amplitude thresholds cannot be out by ~8x",
    quality.assess(good_ch, FS, already_uv=True)["amplitude_uv"]
    < quality.assess(good_ch, FS, uv_per_count=7.9)["amplitude_uv"],
)
b = quality.bands(good_ch, FS)
ok(
    "band powers are FRACTIONS that sum to about 1, not uninterpretable bin sums",
    abs(sum(v for k, v in b.items() if not k.startswith("_")) - 1.0) < 0.05,
)
ok(
    "...and carry the proxy caveat with them, not only in the docs",
    "proxy" in b["_caveat"] and "jaw clench" in b["_caveat"],
)
sp = quality.spectrum(good_ch, FS)
ok("the spectrum reports its own resolution", sp["resolution_hz"] > 0 and len(sp["freqs"]) > 20)

# The UI is the workbench's <signal-panel> (its Monitor tab). This process is the backend it
# calls (/quality, /bands, /spectrum, /extract, /integration-check — all tested above); the
# trace/spectrum/widget-rack markup and its own honesty checks (design system only, no local
# palette, demo labelling, trimmed getPropertyValue) live in
# apps/web/signal-panel/dev_check_js.mjs.
ok(
    "scope.html/scope.js do not live in this process any more",
    not (HERE / "scope.html").exists() and not (HERE / "scope.js").exists(),
)
ok(
    "the merged Monitor panel exists at its new home instead",
    (_SIGNAL_PANEL / "signal-panel.js").exists(),
)
ok(
    "the daemon reports `demo` so no client can mistake generated data for a recording",
    '"demo": self.port_name == self.DEMO_PORT' in serve_src,
)
ok(
    "the demo source is a distinct port name, never a silent fallback from a failed open",
    "DEMO_PORT = " in serve_src and "demo://synthetic" in serve_src,
)
ok(
    "...and eeg-client.js says which band-power implementation is authoritative",
    "authoritative" in (HERE / "eeg-client.js").read_text(),
)


# ============================================================ 13. docs =============
section("4. Documentation")

for name in ("CLAUDE.md", "INTEGRATION.md", "README.md"):
    ok(f"{name} exists", (HERE / name).exists(), name)
integ = (HERE / "INTEGRATION.md").read_text()
ok(
    "INTEGRATION.md documents the acquisition client and the black box",
    all(r in integ for r in ("eeg.connect", "/record", "eeg.status()")),
)
ok("...the measured sample rate", "rateMeasured" in integ)
ok(
    "...and where the moved analysis routes now come from",
    "auditory-atlas" in integ and "signal-detection" in integ,
)
claude = (HERE / "CLAUDE.md").read_text()
_expdoc = HERE.parents[1] / "docs" / "experimental.md"
ok(
    "docs/experimental.md says how the optional tools are found ($OLIMEX_TOOLS)",
    _expdoc.exists() and "OLIMEX_TOOLS" in _expdoc.read_text(),
)
ok("CLAUDE.md keeps the original honesty section", "band power" in claude.lower())
# This repo is public: the bridge's own docs and code carry no path into another repository
# (`projects/...`, `falsify/...`, `tools/...` were the shapes those references took). Checked by
# pattern, so this file does not itself have to name what it is keeping out.
_FOREIGN_PATH = re.compile(r"(?<![\w.-])(projects|falsify|tools)/[\w-]+")
for _f in (
    sorted(HERE.glob("*.md"))
    + [HERE / "validation" / "VALIDATION.md"]
    + sorted(p for p in HERE.glob("*.py") if p.name != "dev_check.py")
    + sorted(HERE.glob("*.js"))
    + sorted((HERE / "validation").glob("*.py"))
):
    _hits = _FOREIGN_PATH.findall(_f.read_text())
    ok(f"{_f.relative_to(HERE)} carries no path into another repository", not _hits, str(_hits))
ok(
    "...and no 'monorepo' framing: this repo stands on its own",
    not any("monorepo" in _f.read_text().lower() for _f in HERE.glob("*.md")),
)

# ---------------------------------------------------------------------------------------
# REGRESSION: `source: "live"` was broken on EVERY extraction route.
#
# `_samples_for` unpacked TWO values out of `read_since`, which returns three
# (samples, new_total, actual_from), so any request carrying `source: "live"` raised
# `too many values to unpack (expected 2, got 3)` and came back 400 — /quality, /bands,
# /spectrum, /integration-check and every /extract* route. That is the live path this
# service exists to own: the process that already holds the port answering "is the response
# there yet" without anyone exporting a file.
#
# It survived because nothing exercised it. Every test here passes `samples` outright, and
# the SSE handler — the only other caller — unpacks three correctly. Found 2026-09-07 by the
# first consumer to ask a real attached rig whether the electrodes were on anything.
_serve_src = (HERE / "serve.py").read_text()
_since_callers = re.findall(
    r"^[ \t]*([A-Za-z_][^\n=]*?)=\s*[A-Za-z_.]*read_since\(", _serve_src, re.M
)
ok("read_since has callers to check", bool(_since_callers), str(_since_callers))
for _lhs in _since_callers:
    _names = [p for p in _lhs.split(",") if p.strip()]
    ok(
        f"read_since unpacked into 3 names, not 2 ({_lhs.strip()})",
        len(_names) == 3,
        "read_since returns (samples, new_total, actual_from)",
    )
ok(
    "_samples_for takes the SAMPLES element, not an index",
    re.search(r"vals,\s*_?total,\s*_?actual_from\s*=\s*DAEMON\.read_since", _serve_src) is not None,
)


# ============================================================ durability =========
section("DURABILITY — a session must never be lost, and a partial one must never look complete")

import durability  # noqa: E402


def _refuses(fn):
    try:
        fn()
        return False
    except durability.DurabilityError:
        return True


_APP = "_devcheck"
try:
    st = durability.disk_selftest(_APP)
    ok("the disk self-test can write and read back", st["ok"], st.get("error"))
    ok("the self-test reports free space", st["free_mb"] is not None)

    w = durability.SessionWriter(_APP, "s1", csv_header="idx,uv", meta={"note": "dev_check"})
    w.init(record={"blocks": []})
    rec = json.loads(w.json_path.read_text())
    # THE load-bearing rule: true from init, so every unanticipated death leaves an honest record.
    ok("terminated_early is TRUE immediately after init", rec["terminated_early"] is True)
    ok(
        "a session that died before acquisition reports has_raw_samples false",
        rec["has_raw_samples"] is False,
    )
    orph = durability.list_orphans(_APP)
    ok("…and is surfaced as an orphan", len(orph) == 1)
    ok(
        "…diagnosed as a write failure, not electrode dropout",
        "WRITE FAILURE" in orph[0]["diagnosis"],
    )

    w.update(record={"blocks": [1]}, csv_rows=["0,512", "1,514"], phase="block-1")
    rec = json.loads(w.json_path.read_text())
    ok("an updated session still carries terminated_early", rec["terminated_early"] is True)
    ok("…and now reports raw samples", rec["has_raw_samples"] and rec["raw_rows"] == 2)
    ok(
        "…diagnosed as interrupted-but-reviewable",
        "reviewable" in durability.list_orphans(_APP)[0]["diagnosis"],
    )
    ok(
        "the raw CSV is appended, header first",
        w.csv_path.read_text().splitlines() == ["idx,uv", "0,512", "1,514"],
    )

    w.update(record={"blocks": [1, 2]}, csv_rows=["2,515"])
    ok("a second update appends rather than truncates", w.rows_written == 3)

    w.finalize(record={"blocks": [1, 2]})
    ok(
        "finalize is the ONLY thing that clears terminated_early",
        json.loads(w.json_path.read_text())["terminated_early"] is False,
    )
    ok("…and the session stops being an orphan", durability.list_orphans(_APP) == [])

    # A writer that TOOK OVER a running session must say the CSV is incomplete, and must keep
    # saying it after later updates overwrite the phase.
    r1 = durability.SessionWriter(_APP, "reatt", csv_header=None)
    r1.init(phase="reattached", reattached=True)
    r1.update(csv_rows=["4,902"], phase="block-5")
    rr = json.loads(r1.json_path.read_text())
    ok("a reattached writer keeps its flag after a later update", rr["reattached"] is True)
    ok("…and declares the raw CSV incomplete", rr["raw_csv_complete"] is False)
    ok("…and says where the missing rows are", "browser failsafe" in rr["reattach_note"])
    ok(
        "…and stamps the warning into the CSV itself, not only the JSON",
        r1.csv_path.read_text().startswith("# REATTACHED"),
    )
    ok(
        "a normal writer is not marked reattached",
        json.loads(w.json_path.read_text())["raw_csv_complete"] is True,
    )

    w2 = durability.SessionWriter(_APP, "aborted", csv_header="idx,uv")
    w2.init()
    w2.update(csv_rows=["0,1"])
    w2.finalize(phase="aborted", terminated_early=True)
    ok(
        "a deliberately aborted session is FINALISED as early-terminated, not abandoned",
        any(o["session"] == "aborted" for o in durability.list_orphans(_APP)),
    )

    # Path components come from the browser and are sanitised, never joined raw.
    ok(
        "a traversal attempt cannot escape recordings/",
        str(durability.RECORDINGS) in str(durability.session_dir("../../etc", "x")),
    )
    ok(
        "an empty app name is refused rather than defaulted",
        _refuses(lambda: durability.session_dir("///", "x")),
    )

    ok(
        "DURABILITY.md exists and states the invariant",
        "clean-looking empty record" in (HERE / "DURABILITY.md").read_text().lower(),
    )
    ok(
        "the shared browser layer is served, like eeg-client.js",
        "/session-recorder.js" in (HERE / "serve.py").read_text(),
    )
    ok(
        "session-recorder.js carries all of L3 and L4",
        all(
            k in (HERE / "session-recorder.js").read_text()
            for k in ("indexedDB", "sendBeacon", "beforeunload", "listOrphans")
        ),
    )
finally:
    shutil.rmtree(durability.RECORDINGS / _APP, ignore_errors=True)


# ============================================================ timebase ============
section("TIMEBASE — the rate the board actually delivers, measured against the host clock")

import timebase  # noqa: E402

# The rig's own case (RIG.md, 2026-09-15): a board 644 ppm slow, read in ~114 ms chunks.
_TRUE = 250.0 / (1 + 644e-6)


def _replay(latency, seconds=123.0, chunk=0.114):
    est = timebase.RateEstimator(250.0)
    t = 0.0
    while t < seconds:
        t += chunk
        est.add(5000.0 + t + latency(t), int(t * _TRUE))
    return est.estimate()


_rng = random.Random(3)
clean = _replay(lambda t: 0.0016 + _rng.expovariate(1 / 0.004))
ok(
    "recovers the rig's measured -644 ppm from clean arrivals, within its own uncertainty",
    clean["measured_hz"] is not None
    and abs(clean["error_ppm"] + 644) <= max(3 * clean["uncertainty_ppm"], 10),
    f"{clean['error_ppm']} ± {clean['uncertainty_ppm']}",
)
# THE REASON FOR THE LOWER ENVELOPE. Buffering that GROWS during a session (a busy reader, a
# stalled tab) adds latency, and a least-squares fit folds that growth straight into the rate.
# Here most chunks are delayed by a ramp reaching ~90 ms, but some still arrive promptly -- as
# real reads do -- and the envelope follows those.
_rng = random.Random(4)
grow = _replay(
    lambda t: 0.0016 + (0.0 if _rng.random() < 0.15 else 0.0007 * t) + _rng.expovariate(1 / 0.003)
)
ok(
    "growing buffering does NOT bias the estimate (lower envelope, not least squares)",
    grow["measured_hz"] is not None and abs(grow["error_ppm"] + 644) <= 25,
    f"{grow['error_ppm']} ppm; a least-squares fit reads -1259 on this same data",
)
# REGRESSION, found on the real rig: re-opening the port delivers lines left in the OS buffer
# INSTANTLY, then the Arduino resets and is silent for 1.62 s. Without the gap restart that early
# instant was its bin's lowest latency and read a -685 ppm clock as -3300 ± 1491.
_TRUE2 = 250.0 / (1 + 685e-6)
_s = timebase.RateEstimator(250.0)
_s.add(7000.0, 2)
_t = 1.62
while _t < 140:
    _t += 0.114
    _s.add(7000.0 + _t + 0.002, 2 + int((_t - 1.62) * _TRUE2))
_stale = _s.estimate()
ok(
    "REGRESSION: stale buffered lines + the board's 1.6 s reboot do not bias the rate",
    _stale["measured_hz"] is not None and abs(_stale["error_ppm"] + 685) <= 15 and _s.restarts == 1,
    f"{_stale['error_ppm']} ± {_stale['uncertainty_ppm']}, restarts {_s.restarts}",
)
_rng = random.Random(2)
_b = timebase.RateEstimator(250.0)
_t = 0.0
while _t < 140:
    _t += 0.114
    _b.add(
        8000.0 + _t + 0.002 + (0.3 if 60 < _t < 62 else 0.0) + _rng.expovariate(1 / 0.004),
        int(_t * _TRUE2),
    )
ok(
    "a BUFFERED stall (samples arrive late, but keep arriving) does not restart the estimate",
    _b.restarts == 0 and abs(_b.estimate()["error_ppm"] + 685) <= 15,
)

_e = timebase.RateEstimator(250.0)
for _i in range(1, 60):
    _e.add(100.0 + _i * 0.4, _i * 100)  # ~24 s of data
_early = _e.estimate()
ok("under 30 s there is NO measured rate -- null, never a default", _early["measured_hz"] is None)
ok("...and the null says what it is waiting for", "needs 30 s" in _early["basis"])
_e.add(200.0, 50)  # counter went backwards
ok("a counter that restarts (a re-opened port) resets the estimate", _e.estimate()["bins"] == 0)
ok(
    "the uncertainty is labelled statistical, not a claim about the host clock",
    "few ppm" in clean["basis"] and "no samples lost" in clean["basis"],
)

_srv = (HERE / "serve.py").read_text()
ok(
    "status reports the measured rate beside the declared one",
    all(
        k in _srv
        for k in (
            '"rateDeclared"',
            '"rateMeasured"',
            '"rateErrorPpm"',
            '"rateUncertaintyPpm"',
            '"rateBasis"',
        )
    ),
)
ok(
    "`rate` itself stays DECLARED, and the code says it is not a measurement",
    '"rate": DEFAULT_RATE,' in _srv and "It is NOT a measurement" in _srv,
)
ok(
    "the reader timestamps a chunk BEFORE parsing it",
    _srv.index("arrived = time.monotonic()")
    < _srv.index('carry += data.decode("ascii", "ignore")'),
)
ok(
    "the estimate resets on every (re)open, real port and demo",
    _srv.count("self.rate_est.reset()") == 2,
)
_exp_src = (HERE / "experimental.py").read_text()
ok(
    "live extraction uses the measured rate when it exists, and says which it used",
    '"measured"' in _srv
    and '"rate_basis": rate_basis' in _exp_src
    and "rate, _basis = _rate_for(body)" in _srv,
)
ok("a caller who states a rate keeps it", 'return float(body["rate"]), "caller"' in _srv)
ok(
    "timebase is stdlib-only, so it cannot take acquisition down",
    not re.search(r"^\s*(import|from)\s+(numpy|scipy)", (HERE / "timebase.py").read_text(), re.M),
)


# ============================================================ stream integrity ====
section("STREAM INTEGRITY — dropped and malformed samples are counted, never repaired")

_si = timebase.StreamIntegrity(250.0)
_steps = [0, 4000, 8004, 12000, 20000, 24004, 28000]  # one missing sample between 12000 and 20000
_kinds = [_si.add(t)[0] for t in _steps]
ok("a first sample has no step", _kinds[0] is None)
ok("board jitter (3988-4012 us) is not a gap", _kinds[1:4] == ["ok", "ok", "ok"], str(_kinds))
ok(
    "a doubled step is ONE gap with one missing sample, and its size is kept",
    _si.gaps == 1 and _si.missing_estimate == 1 and _si.max_gap_us == 8000,
    json.dumps(_si.snapshot()),
)
_w = timebase.StreamIntegrity(250.0)
_w.add(2**32 - 2000)
_wk = _w.add(2000)
ok(
    "the micros() 32-bit wraparound (~71.6 min) is a normal step, not a gap or a reset",
    _wk == ("ok", 4000) and _w.wraps == 1 and _w.gaps == 0 and _w.clock_resets == 0,
    str(_wk),
)
_w.add(2000 + 4000 * 10)  # ten periods later: 9 missing
ok("...and a gap across the wrap is still measured", _w.gaps == 1 and _w.missing_estimate == 9)
_r = timebase.StreamIntegrity(250.0)
_r.add(90_000_000)
ok(
    "a board reboot (t_us jumps backwards) is a clock reset, not a 71-minute gap",
    _r.add(1000)[0] == "reset" and _r.gaps == 0 and _r.clock_resets == 1,
)
_d = timebase.StreamIntegrity(250.0)
_d.add(0)
ok("a duplicated line is a short step", _d.add(0)[0] == "short" and _d.short_steps == 1)

ok("a good line parses positionally", serve.parse_line("10432,512,498", 1) == (10432, 512.0))
ok("...and channel_col picks the column", serve.parse_line("10432,512,498", 2) == (10432, 498.0))
ok("a comment or blank line is not an error", serve.parse_line("# ArduinoEKG ready") is None)
ok("a truncated line is an error", serve.parse_line("10432", 1) is False)
ok(
    "a garbled t_us is an error -- it no longer shifts ch1 into ch0",
    serve.parse_line("1x0432,512,498", 1) is False,
)
ok("a garbled value is an error", serve.parse_line("10432,5?2,498", 1) is False)
ok("NaN is an error, not a sample", serve.parse_line("10432,nan,498", 1) is False)


class _FakePort:
    """Serves canned bytes to the real `_reader`, then stops the daemon."""

    def __init__(self, daemon, chunks):
        self.daemon, self.chunks = daemon, list(chunks)

    def read(self, _n):
        if self.chunks:
            return self.chunks.pop(0)
        with self.daemon.lock:
            self.daemon.running = False
        return b""

    def close(self):
        pass


_tmp_rec = Path(__import__("tempfile").mkdtemp())
_old_rec_dir = serve.REC_DIR
serve.REC_DIR = str(_tmp_rec)
try:
    _dm = serve.SerialDaemon()
    _lines = ["xx,999,1\n", "# ArduinoEKG ready\n"]  # a mid-line fragment at open, then a banner
    _lines += [f"{4000 * i},{500 + i},1\n" for i in range(5)]  # 0..16000
    _lines += ["20000,5??,1\n"]  # malformed: dropped and counted
    _lines += [f"{4000 * i},{500 + i},1\n" for i in range(7, 10)]  # 28000: a gap of 12000
    _payload = "".join(_lines).encode()
    _dm.port, _dm.port_name, _dm.baud, _dm.running, _dm.generation = (
        _FakePort(_dm, []),
        "fake",
        1,
        True,
        1,
    )
    _dm.start_record("integrity")
    _dm.port.chunks = [_payload[:7], _payload[7:40], _payload[40:]]
    _dm._reader(1)
    _st = _dm.status()
    _stop = _dm.stop_record()
    ok("the reader keeps only well-formed samples", _dm.total == 8, str(_dm.total))
    ok(
        "no sample is inserted to fill a gap",
        _dm.buf == [500.0, 501.0, 502.0, 503.0, 504.0, 507.0, 508.0, 509.0],
        str(_dm.buf),
    )
    ok(
        "/status reports parse errors, gaps and the largest gap",
        _st["parseErrors"] == 1 and _st["streamGaps"] == 1 and _st["maxGapUs"] == 12000,
        json.dumps(_st["stream"]),
    )
    ok(
        "...and the full record, with its basis, under `stream`",
        _st["stream"]["missing_estimate"] == 2 and "t_us" in _st["stream"]["basis"],
    )
    ok(
        "/record/stop reports what the wire lost WHILE recording",
        _stop["recParseErrors"] == 1 and _stop["recGaps"] == 1 and _stop["recMaxGapUs"] == 12000,
        json.dumps(_stop),
    )
    _bb = serve.read_black_box(_stop["recPath"])
    ok(
        "the black box now carries the board's t_us per sample",
        _bb["columns"] == ["sample_index", "value", "t_us"]
        and [r[2] for r in _bb["rows"]] == [0, 4000, 8000, 12000, 16000, 28000, 32000, 36000],
        str(_bb["rows"][:3]),
    )
    ok(
        "...and its last line says what was lost",
        _bb["header"][-1].startswith("# stopped") and "gaps=1" in _bb["header"][-1],
    )
    _old = _tmp_rec / "old.csv"
    _old.write_text(
        "# eeg-bridge port=x baud=1 channel_col=1 started_total=0\n"
        "sample_index,value\n0,512.0\n1,513.0\n"
    )
    _ob = serve.read_black_box(_old)
    ok(
        "an OLDER black box without t_us still reads",
        _ob["columns"] == ["sample_index", "value"]
        and _ob["rows"] == [(0, 512.0, None), (1, 513.0, None)],
    )
finally:
    serve.REC_DIR = _old_rec_dir
    shutil.rmtree(_tmp_rec, ignore_errors=True)


# ============================================================ CORS ================
section("CORS — loopback and an explicit allow-list, never `*`")

ok("http://127.0.0.1:<any port> is allowed", serve.origin_allowed("http://127.0.0.1:8150"))
ok("http://localhost:<any port> is allowed", serve.origin_allowed("http://localhost:5173"))
ok("an arbitrary site is not", not serve.origin_allowed("https://evil.example"))
ok(
    "a look-alike host is not",
    not serve.origin_allowed("http://localhost.evil.example:80")
    and not serve.origin_allowed("http://127.0.0.1.evil.example"),
)
os.environ["OLIMEX_ALLOWED_ORIGINS"] = "https://lab.example, http://10.0.0.5:8150"
ok(
    "$OLIMEX_ALLOWED_ORIGINS adds exact origins",
    serve.origin_allowed("https://lab.example") and serve.origin_allowed("http://10.0.0.5:8150"),
)
ok("...and only those", not serve.origin_allowed("https://lab.example.evil"))
os.environ.pop("OLIMEX_ALLOWED_ORIGINS")

import threading  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

_srv_http = serve.ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
threading.Thread(target=_srv_http.serve_forever, daemon=True).start()
_base = f"http://127.0.0.1:{_srv_http.server_address[1]}"


def _hdrs(origin):
    req = urllib.request.Request(_base + "/status", headers={"Origin": origin})
    with urllib.request.urlopen(req, timeout=5) as r:
        return dict(r.headers), json.loads(r.read())


_h, _status = _hdrs("http://localhost:8150")
ok(
    "a loopback Origin is echoed back, with Vary: Origin",
    _h.get("Access-Control-Allow-Origin") == "http://localhost:8150" and _h.get("Vary") == "Origin",
)
_h2, _ = _hdrs("https://evil.example")
ok("a foreign Origin gets no Allow-Origin header", "Access-Control-Allow-Origin" not in _h2)
ok(
    "/status carries the integrity counts over HTTP",
    {"parseErrors", "streamGaps", "maxGapUs", "stream"} <= set(_status),
)
_q = urllib.request.Request(
    _base + "/quality",
    data=json.dumps(
        {"samples": _small, "rate": 250, "uv_per_count": 7.9, "cfg": {"readout": "ecg"}}
    ).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(_q, timeout=10) as _r:
    _qh = json.loads(_r.read())
ok(
    "POST /quality takes the readout from `cfg` (what the panel forwards)",
    _qh["readout"] == "ecg"
    and _qh["alpha_snr"] is None
    and _qh["method"] == "plausibility heuristic",
)
_x = urllib.request.Request(
    _base + "/extract",
    data=json.dumps({"samples": [0.0] * 10}).encode(),
    headers={"Content-Type": "application/json"},
)
try:
    urllib.request.urlopen(_x, timeout=10)
    _xe = {}
except urllib.error.HTTPError as _he:
    _xe = json.loads(_he.read())
ok(
    "an experimental route's error or 503 is itself marked experimental",
    _xe.get("experimental") is True and _xe.get("note"),
    json.dumps(_xe)[:200],
)
_srv_http.shutdown()


# ============================================================ eeg-client.js =======
section("eeg-client.js — experimental, and consistent with the server where it overlaps")

_client = (HERE / "eeg-client.js").read_text()
ok(
    "bands() and iaf() are marked deprecated/experimental",
    _client.count("@deprecated EXPERIMENTAL") >= 2,
)
ok(
    "iaf() refuses a maximum that is not a true local peak",
    "if (best <= 0 || best >= ps.length - 1) return null;" in _client,
)
_node = shutil.which("node")
if _node:
    _sig = [
        512
        + 20 * math.sin(2 * math.pi * 10.2 * k / FS)
        + 8 * math.sin(2 * math.pi * 21 * k / FS)
        + 5 * math.sin(2 * math.pi * 3 * k / FS)
        for k in range(1000)
    ]
    _js = (
        "require(process.argv[1]); const c = new globalThis.EEGClient({rate:250, ringSec:4});"
        f"const xs = {json.dumps(_sig)};"
        "for (const v of xs) { c.ring[c.w] = v; c.w = (c.w + 1) % c.ring.length; c.filled++; }"
        "const b = c.bands(4); const ramp = new globalThis.EEGClient({rate:250, ringSec:4});"
        "for (let i = 0; i < 1000; i++) { ramp.ring[i] = i; } ramp.filled = 1000;"
        "console.log(JSON.stringify({b, iafRamp: ramp.iaf(4)}));"
    )
    _out = subprocess.run(
        [_node, "-e", _js, str(HERE / "eeg-client.js")], capture_output=True, text=True
    )
    if _out.returncode == 0:
        _jb = json.loads(_out.stdout)
        _sb = quality.bands(_sig, FS)
        ok(
            "client bands() relative shares match the server's /bands",
            all(
                abs(_jb["b"][k + "Rel"] - _sb[k]) < 1e-3
                for k in ("delta", "theta", "alpha", "beta", "gamma")
            ),
            json.dumps({k: (_jb["b"][k + "Rel"], _sb[k]) for k in ("alpha", "beta")}),
        )
        ok("iaf() returns null on a monotonic ramp (no peak)", _jb["iafRamp"] is None)
    else:
        ok("eeg-client.js runs under node", False, _out.stderr[-300:])
else:
    print("  SKIP client/server band parity -- node not installed")


# ============================================================ summary ==============
print()
for f in FAILURES:
    print(f"  \033[31mFAIL\033[0m {f}")
total = PASS + FAIL
colour = "\033[32m" if FAIL == 0 else "\033[31m"
print(f"\n{colour}{PASS}/{total}\033[0m checks passed")
sys.exit(1 if FAIL else 0)
