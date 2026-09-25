#!/usr/bin/env python3
"""dev_check.py -- the workbench's gate. Runs the real server in-process on a free port, with no
bridge, and a throwaway session store.

    python3 apps/web/dev_check.py

Wraps dev_check_js.mjs (playback helpers) and the placement gate; skips the JS loudly without node.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
P, F, S = [], [], []


def ok(n, c, note=""):
    (P if c else F).append(f"{n}{(' -- ' + note) if note else ''}")


store = tempfile.mkdtemp()
exports = tempfile.mkdtemp()
os.environ.update(
    {
        "OLIMEX_SESSIONS": store,
        "OLIMEX_EXPORTS": exports,
        "OLIMEX_UPLOADER": "none",
        "OLIMEX_BRIDGE": "http://127.0.0.1:9",
    }
)  # port 9: nothing answers
sys.path.insert(0, str(HERE))
import serve  # noqa: E402

# After serve: readouts.py puts apps/server first on sys.path, where another serve.py lives.
readouts_mod = serve.readouts

sock = socket.socket()
sock.bind(("127.0.0.1", 0))
port = sock.getsockname()[1]
sock.close()
srv = serve.ThreadingHTTPServer(("127.0.0.1", port), serve.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"


def get(path, raw=False):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            data = r.read()
            return r.status, (data if raw else json.loads(data or b"{}"))
    except urllib.error.HTTPError as e:
        data = e.read()
        try:
            return e.code, (data if raw else json.loads(data or b"{}"))
        except ValueError:
            return e.code, data


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


try:
    # --------------------------------------------------------------------------- static --
    for path in (
        "/",
        "/app.js",
        "/playback.js",
        "/app.css",
        "/design/design.css",
        "/design/design.js",
        "/design/icons/polarize-icons.svg",
        "/signal-panel/signal-panel.js",
        "/signal-panel/signal-panel.css",
    ):
        code, _ = get(path, raw=True)
        ok(f"serves {path}", code == 200, str(code))
    fonts = sorted(p.name for p in (HERE / "vendor" / "design" / "fonts").glob("*.woff2"))
    ok(
        "serves every vendored font by prefix",
        fonts and all(get(f"/design/fonts/{f}", raw=True)[0] == 200 for f in fonts),
    )
    for path in (
        "/serve.py",
        "/placement/placement.py",
        "/vendor/design/design.css",
        "/../README.md",
        "/signal-panel/dev_check.py",
        "/.git/config",
    ):
        code, _ = get(path, raw=True)
        ok(f"does NOT serve {path}", code != 200, str(code))

    # --------------------------------------------------------------------------- the API --
    code, r = get("/api/readouts")
    ok(
        "readouts list EEG, ECG and EMG",
        code == 200 and [x["key"] for x in r["readouts"]] == ["eeg", "ecg", "emg"],
    )
    ok("...and EDA is a stated refusal, not an absence", "eda" in r["refused"])
    code, r = get("/api/gate?readout=eda")
    ok(
        "asking for EDA is a 400 with the reason",
        code == 400 and "NOT AN EDA AMPLIFIER" in r["error"],
    )
    code, g = get("/api/hookup?readout=ecg")
    ok("the hookup guide carries a diagram", code == 200 and g["svg"].startswith("<svg"))
    ok("...the FULL safety list (11 lines)", len(g["safety"]) == 11)
    _safety = " ".join(g["safety"])
    for phrase in (
        "NOT a medical device",
        "BATTERY-POWERED",
        "Unplug EVERY mains-connected device",
        "HDMI",
        "powered USB hub or dock",
        "Ethernet",
        "headphone amplifier",
        "isolate the USB data line too",
        "IEC 60601-1",
        "pacemaker, ICD",
        "path across the chest",
        "both arms or on both sides of the chest",
        "grounded metal",
        "broken skin",
        "stings, burns, itches or reddens",
        "applies no current",
        "One person, one rig, one session",
    ):
        ok(f"...the safety list still says {phrase!r}", phrase in _safety)
    ok(
        "...and never offers a merely 'properly isolated' supply as sufficient",
        "or from a properly isolated supply" not in _safety,
    )
    ok("...a ground in the montage", any(m["role"] == "ground" for m in g["montage"]))
    ok(
        "the prep list does not attribute the rig's noise spread to prep",
        "prep, not software" not in json.dumps(g["prep"]) and "11.7x" in json.dumps(g["prep"]),
    )

    # --------------------------------------------------------------------- the montages --
    code, g = get("/api/hookup?readout=eeg")
    sites = {m["role"]: m["site"] for m in g["montage"]}
    ok(
        "the EEG active electrode is on Oz, not the inion (a measuring landmark)",
        sites.get("active") == "Oz (occipital)"
        and all(m["site"] not in ("inion", "nasion") for m in g["montage"]),
        f"{sites}",
    )
    ok(
        "...the head positions are described as ESTIMATED 10-20 positions",
        "estimated 10-20" in json.dumps(g).lower(),
    )
    ok(
        "...and the Cz note uses the preauricular points, not the ear canals",
        any(
            r["site"] == "Cz (vertex)" and "preauricular" in r["where"]
            for r in g["checklist"]["rows"]
        ),
    )
    ok("...and the EEG diagram's labels do not overlap", not g["label_collisions"])
    code, g = get("/api/hookup?readout=emg")
    act = next(m["site"] for m in g["montage"] if m["role"] == "active")
    ref = next(m["site"] for m in g["montage"] if m["role"] == "reference")
    ok(
        "EMG is a bipolar pair over one belly (SENIAM), not belly-tendon",
        act.startswith("FDI belly") and ref.startswith("FDI belly") and act != ref,
        f"{act} / {ref}",
    )
    ok(
        "...and the readout says the 40 Hz analog low-pass removes most of the EMG band",
        "40 Hz" in readouts_mod.READOUTS["emg"]["feature_note"],
    )
    ok("...and the EMG diagram's labels do not overlap", not g["label_collisions"])
    code, st = get("/api/storage")
    ok(
        "storage status says no uploader and where sessions go",
        code == 200 and st["uploader"] == "none" and st["store"] == store,
    )

    code, r = get("/bridge/status")
    ok(
        "a down bridge is a 503 that says the bridge owns the port",
        code == 503 and "owns the serial port" in r["note"],
    )

    # --------------------------------------------------- record -> list -> play -> export --
    code, r = post(
        "/dataset/start",
        {
            "project": "olimex-shield",
            "readout": "eeg",
            "source": "electrode",
            "rate_hz": 250,
            "electrodes_on_at": 1,
            "montage": [{"role": "reference", "site": "Cz (vertex)"}],
        },
    )
    stamp = r.get("stamp")
    ok("Record opens a session through /dataset/start", code == 200 and stamp)
    post("/dataset/append", {"stamp": stamp, "values": [510 + (i % 5) for i in range(500)]})
    post("/dataset/tag", {"stamp": stamp, "label": "eyes closed", "t_s": 1.0})
    code, _ = post("/api/upload", {"stamp": stamp})
    ok("uploading a session still recording is refused", code == 400)
    code, r = post("/dataset/stop", {"stamp": stamp})
    ok("Stop closes it", code == 200 and r["meta"]["n_samples"] == 500)
    code, r = post(
        "/dataset/annotate",
        {"stamp": stamp, "rate_measured_hz": 249.83, "rate_basis": "host clock"},
    )
    ok("the measured rate is annotated after stop", code == 200)
    code, r = get("/api/sessions")
    row = next((s for s in r["sessions"] if s["stamp"] == stamp), None)
    ok(
        "the session is listed with its length inputs and upload count",
        row and row["n_samples"] == 500 and row["rate_hz"] == 250 and row["uploads"] == 0,
    )
    code, r = get(f"/api/session?id={stamp}&seconds=86400")
    ok(
        "playback gets every sample and the tags",
        code == 200 and len(r["values"]) == 500 and r["tags"][0]["label"] == "eyes closed",
    )
    code, r = get("/api/session?id=../../etc")
    ok("a session id that walks out of the store is refused", code == 400)
    code, r = post("/api/upload", {"stamp": stamp})
    ok(
        "uploading with no uploader configured is a 400 saying so",
        code == 400 and "no uploader" in r["error"],
    )
    code, r = post("/api/export/bids", {"stamp": stamp, "subject": "01", "task": "rest"})
    ok(
        "BIDS export writes a BrainVision header",
        code == 200 and r["header"].endswith("sub-01_task-rest_eeg.vhdr"),
    )
    side = json.loads(Path(r["header"]).with_name("sub-01_task-rest_eeg.json").read_text())
    ok("...carrying the annotated measured rate", side.get("SamplingFrequencyMeasured") == 249.83)
    code, r = post("/api/export/bids", {"stamp": stamp, "subject": "Jane Doe"})
    ok(
        "a subject label that could be a name is refused",
        code == 400 and "alphanumeric" in r["error"],
    )

    # ------------------------------------------------------------------- page contracts --
    app = (HERE / "app.js").read_text()
    html = (HERE / "index.html").read_text()
    ok("the hookup guide is the panel's beforeConnect", "p.beforeConnect = hookupGate" in app)
    gate = app[app.index("async function hookupGate") : app.index("function sessionMeta")]
    ok(
        "a failed guide fetch returns false before the dialog",
        gate.index("return false") < gate.index("askHookup()"),
    )
    ok(
        "electrodes_on_at is when the operator confirmed, never 'now' at Record",
        "electrodes_on_at: S.hookupAt" in app,
    )
    ok(
        "the page mounts the panel with a long enough ring, and the Atlas tab only on demand",
        'ring="120"' in html
        and not re.search(r"<signal-panel[^>]*\batlas\b", html)
        and 'if (t.atlas) panel().setAttribute("atlas", "")' in app,
    )
    code, tl = get("/api/tools")
    ok("/api/tools says which optional companion tools are present", code == 200 and "atlas" in tl)
    if tl.get("atlas"):
        code, _ = get("/signal-panel/atlas-panel.js", raw=True)
        ok("with auditory-atlas present, the atlas panel is served from there", code == 200)
    else:
        S.append("atlas panel served -- auditory-atlas tool not reachable from here")
    _old = os.environ.get("OLIMEX_TOOLS")
    os.environ["OLIMEX_TOOLS"] = "/nonexistent"
    code, tl2 = get("/api/tools")
    code2, _ = get("/signal-panel/atlas-panel.js", raw=True)
    ok(
        "with no tools present the atlas is reported absent and its file is not served",
        tl2["atlas"] is False and tl2["note"] and code2 != 200,
    )
    if _old is None:
        os.environ.pop("OLIMEX_TOOLS")
    else:
        os.environ["OLIMEX_TOOLS"] = _old
    ok(
        "no asset path is root-relative (a sub-path mount would break)",
        not re.search(r'(href|src)="/', html),
    )
    css = (HERE / "app.css").read_text()
    css_code = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    ok(
        "app.css has no colour literal",
        not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", css_code),
    )
    ok(
        "app.css has no font-family or font-size literal",
        not re.search(r"font-(family|size)\s*:", css_code),
    )
    ok(
        "the workbench binds 127.0.0.1 unless told otherwise",
        'ap.add_argument("--bind", default="127.0.0.1")' in (HERE / "serve.py").read_text(),
    )

    # ----------------------------------------------------- the vendored design system --
    upstream = next(
        (
            u / "design"
            for u in REPO.parents
            if (u / "design" / "design.css").is_file() and (u / "design" / "tokens.json").is_file()
        ),
        None,
    )
    if upstream is None:
        S.append("vendored design == upstream -- no upstream design checkout beside this repo")
    else:
        drift = [
            f
            for f in ("design.css", "design.js", "tokens.json", "icons/polarize-icons.svg")
            if (upstream / f).read_bytes() != (HERE / "vendor" / "design" / f).read_bytes()
        ]
        ok(
            "vendored design matches the upstream design system (run scripts/sync_design.py)",
            not drift,
            f"{drift}",
        )
finally:
    srv.shutdown()
    shutil.rmtree(store, ignore_errors=True)
    shutil.rmtree(exports, ignore_errors=True)

# ----------------------------------------------------------------------------- wrapped --
if shutil.which("node"):
    r = subprocess.run(["node", str(HERE / "dev_check_js.mjs")], capture_output=True, text=True)
    print(r.stdout.strip())
    ok(
        "dev_check_js.mjs passes",
        r.returncode == 0,
        r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:],
    )
else:
    S.append("dev_check_js.mjs -- node not installed; playback helpers NOT checked")

for s in S:
    print(f"  SKIP {s}")
for f in F:
    print(f"  FAIL {f}")
print(f"\nweb/dev_check: {len(P)}/{len(P) + len(F)} passed")
sys.exit(1 if F else 0)
