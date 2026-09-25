#!/usr/bin/env python3
"""dev_check_storage.py -- the gate for storage.py (uploads) and bids.py (export).

    python3 apps/server/dev_check_storage.py

No network and no bucket: uploads are exercised through an in-process fake plugin (the real one
is the host's, e.g. an optional companion upload tool). The BIDS export is read back with
MNE-BIDS when it is installed -- an independent reader -- and that half SKIPS LOUDLY when it is
not.
"""

import json
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
P, F, S = [], [], []


def ok(n, c, note=""):
    (P if c else F).append(f"{n}{(' -- ' + note) if note else ''}")


def raises(name, fn, contains=""):
    try:
        fn()
        ok(name, False, "did not raise")
    except Exception as e:
        ok(name, contains.lower() in str(e).lower(), f"{type(e).__name__}: {str(e)[:100]}")


def record(
    D, *, source="electrode", n=500, rate=250.0, tags=(("eyes closed", 0.4),), readout="eeg", **kw
):
    body = {
        **kw,
        "project": "gate",
        "readout": readout,
        "source": source,
        "rate_hz": rate,
        "electrodes_on_at": 1,
        "montage": [
            {"role": "reference", "site": "Cz (vertex)"},
            {"role": "ground", "site": "M2 (right mastoid)"},
        ],
    }
    st = D.start(body)["stamp"]
    D.append({"stamp": st, "values": [512 + (i % 7) for i in range(n)]})
    for lab, t in tags:
        D.tag({"stamp": st, "label": lab, "t_s": t})
    return st


with tempfile.TemporaryDirectory() as store, tempfile.TemporaryDirectory() as out:
    os.environ["OLIMEX_SESSIONS"] = store
    os.environ.pop("OLIMEX_MAINS_HZ", None)
    for k in [k for k in os.environ if k.startswith("OLIMEX_UPLOADER")]:
        del os.environ[k]
    import bids
    import sessions as D
    import storage

    # ------------------------------------------------------------------ storage: refusals --
    _src = (HERE / "storage.py").read_text()
    ok(
        "storage.py carries no storage client of its own -- one upload implementation, not two",
        "boto3" not in _src and "put_object" not in _src,
    )
    st = record(D)
    raises("a session still recording is refused", lambda: storage.upload(st), "still recording")
    D.stop({"stamp": st})
    ok(
        "the default uploader is none",
        storage.status()["uploader"] == "none" and storage.status()["ready"] is False,
    )
    raises(
        "uploading with no uploader configured says so rather than pretending",
        lambda: storage.upload(st),
        "no uploader configured",
    )
    os.environ["OLIMEX_UPLOADER"] = "dropbox-maybe"
    ok(
        "an unknown uploader is not silently treated as none",
        "unknown uploader" in (storage.status()["reason"] or ""),
    )
    raises("...and uploading with it raises", lambda: storage.upload(st), "unknown uploader")
    raises(
        "a stamp that walks out of the store is refused",
        lambda: storage.upload("../../etc"),
        "not a session id",
    )

    os.environ["OLIMEX_UPLOADER"] = "s3"
    ok(
        "'s3' is no longer a built-in and is reported as unknown, not silently accepted",
        "unknown uploader" in (storage.status()["reason"] or ""),
    )

    # ------------------------------------------------------------------- storage: plugin --
    calls = []
    mod = types.ModuleType("fake_uploader")
    seen_files = []
    mod.up = lambda d, stamp, meta: (
        (
            calls.append((Path(d).name, stamp, meta["project"])),
            seen_files.append(sorted(p.name for p in Path(d).iterdir())),
        )[0]
        or {"target": "x"}
    )
    mod.bad = lambda d, stamp, meta: "done"
    sys.modules["fake_uploader"] = mod
    os.environ["OLIMEX_UPLOADER"] = "fake_uploader:up"
    ok("a plugin uploader reports ready", storage.status()["ready"] is True)
    r = storage.upload(st)
    ok("the plugin receives the session dir, stamp and meta", calls == [(st, st, "gate")])
    ok("its receipt is recorded with the uploader's name", r["uploader"] == "fake_uploader:up")
    ok("...and says how many files went", r["files"] == 2)
    r2 = storage.upload(st)
    ok(
        "a second upload still hands over only the data files",
        seen_files[-1] == ["samples.csv", "session.json"],
    )
    ok(
        "the plugin sees the session's data files and NOT an earlier upload's receipts",
        len(storage.receipts(st)) == 2 and seen_files[0] == ["samples.csv", "session.json"],
        f"{seen_files}",
    )
    os.environ["OLIMEX_UPLOADER"] = "fake_uploader:bad"
    raises(
        "a plugin that returns no receipt is a failure", lambda: storage.upload(st), "not a receipt"
    )
    os.environ["OLIMEX_UPLOADER"] = "no_such_module:up"
    ok("a plugin that cannot load says why", "could not be loaded" in storage.status()["reason"])
    os.environ["OLIMEX_UPLOADER"] = "none"

    # ------------------------------------------------------------------------ BIDS export --
    res = bids.export(st, out, subject="01", task="rest")
    root = Path(out)
    hdr = Path(res["header"])
    ok(
        "a BIDS tree is written",
        (root / "dataset_description.json").exists()
        and hdr.exists()
        and hdr.name == "sub-01_task-rest_eeg.vhdr",
    )
    for suffix in ("_eeg.json", "_channels.tsv", "_events.tsv", "_eeg.vmrk", "_eeg.eeg"):
        ok(f"...with {suffix}", (hdr.parent / f"sub-01_task-rest{suffix}").exists())
    side = json.loads((hdr.parent / "sub-01_task-rest_eeg.json").read_text())
    ok(
        "required EEG sidecar fields are present",
        {"TaskName", "SamplingFrequency", "PowerLineFrequency", "SoftwareFilters", "EEGReference"}
        <= set(side),
    )
    ok("the hardware band is recorded as HardwareFilters", "HighpassHz" in json.dumps(side))
    ok("the scaling basis is stated, not implied", "UV_PER_COUNT" in side["Scaling"])
    ok(
        "the reference and ground come from the montage",
        side["EEGReference"] == "Cz (vertex)" and side["EEGGround"] == "M2 (right mastoid)",
    )
    ev = (hdr.parent / "sub-01_task-rest_events.tsv").read_text().splitlines()
    ok("the tag track becomes events.tsv", len(ev) == 2 and "eyes closed" in ev[1])
    ok(
        "participants.tsv holds an id and nothing else",
        (root / "participants.tsv").read_text().split() == ["participant_id", "sub-01"],
    )
    ok(
        "the binary holds one float32 per sample",
        (hdr.parent / "sub-01_task-rest_eeg.eeg").stat().st_size == 4 * 500,
    )
    raises(
        "a subject label that is not alphanumeric is refused (no names in filenames)",
        lambda: bids.export(st, out, subject="Jane Doe"),
        "alphanumeric",
    )
    # ------------------------------------------------ R4: mains, version, provenance, README --
    ok(
        "PowerLineFrequency is 'n/a' when neither the session nor $OLIMEX_MAINS_HZ says -- "
        "never the bench's 60 assumed",
        side["PowerLineFrequency"] == "n/a",
        repr(side["PowerLineFrequency"]),
    )
    ok(
        "the scaling provenance travels with the export: built-in cal, nominal, not verified",
        "built-in cal" in side["ScalingProvenance"]
        and "not externally verified" in side["ScalingProvenance"]
        and "built-in cal" in side["Scaling"],
    )
    _ver = D.software_version()
    ok(
        "SoftwareVersions names the chain version from pyproject.toml",
        _ver != "unknown" and f"olimex-shield {_ver}" in side["SoftwareVersions"],
        side["SoftwareVersions"],
    )
    ddesc = json.loads((root / "dataset_description.json").read_text())
    ok(
        "...and so does GeneratedBy",
        ddesc["GeneratedBy"][0].get("Version") == _ver,
    )
    ok(
        "License and Authors are absent unless supplied -- never invented, never a name by default",
        "License" not in ddesc and "Authors" not in ddesc,
    )
    ok("a root README is written when the dataset has none", (root / "README").is_file())
    ok(
        "...saying what the scale is and where it came from",
        "built-in cal" in (root / "README").read_text(),
    )
    (root / "README").write_text("the operator's own README\n")
    bids.export(st, out, subject="09", task="rest")
    ok(
        "...and an existing README is never overwritten",
        (root / "README").read_text() == "the operator's own README\n",
    )

    os.environ["OLIMEX_MAINS_HZ"] = "50"
    with tempfile.TemporaryDirectory() as o2:
        r50 = bids.export(st, o2, subject="01")
        s50 = json.loads(Path(r50["header"]).with_suffix(".json").read_text())
        ok(
            "with $OLIMEX_MAINS_HZ set, PowerLineFrequency takes it",
            s50["PowerLineFrequency"] == 50.0,
        )
    os.environ.pop("OLIMEX_MAINS_HZ")
    st60 = record(D, mains_hz=60)
    D.stop({"stamp": st60})
    with tempfile.TemporaryDirectory() as o3:
        r60 = bids.export(st60, o3, subject="01", license="CC0", authors=["A. Researcher"])
        s60 = json.loads(Path(r60["header"]).with_suffix(".json").read_text())
        d60 = json.loads((Path(o3) / "dataset_description.json").read_text())
        ok("the session's own mains_hz wins", s60["PowerLineFrequency"] == 60.0)
        ok(
            "License and Authors are written when supplied",
            d60.get("License") == "CC0" and d60.get("Authors") == ["A. Researcher"],
        )

    # ECG / EMG: the eeg datatype, but typed truthfully and counted.
    ecg = record(D, readout="ecg")
    D.stop({"stamp": ecg})
    emg = record(D, readout="emg")
    D.stop({"stamp": emg})
    with tempfile.TemporaryDirectory() as o4:
        re_ = bids.export(ecg, o4, subject="01", task="rest")
        se = json.loads(Path(re_["header"]).with_suffix(".json").read_text())
        ch = Path(re_["header"]).with_name("sub-01_task-rest_channels.tsv").read_text()
        ok(
            "an ECG session is typed ECG with ECGChannelCount 1 and EEGChannelCount 0",
            re_["channel_type"] == "ECG"
            and se["ECGChannelCount"] == 1
            and se["EEGChannelCount"] == 0
            and "\tECG\t" in ch,
        )
        ok(
            "...and says in its sidecar that it is not EEG",
            "not EEG" in se.get("RecordingNote", ""),
        )
        rm_ = bids.export(emg, o4, subject="02", task="rest")
        sm = json.loads(Path(rm_["header"]).with_suffix(".json").read_text())
        ok(
            "an EMG session is typed EMG with EMGChannelCount 1",
            rm_["channel_type"] == "EMG"
            and sm["EMGChannelCount"] == 1
            and sm["EEGChannelCount"] == 0,
        )
        ok("an EEG session carries no such note", "RecordingNote" not in side)

    # SYNTHETIC: refused by default, and never mixed into a real dataset or vice versa.
    syn = record(D, source="synthetic")
    D.stop({"stamp": syn})
    raises(
        "a SYNTHETIC session is refused by default",
        lambda: bids.export(syn, out, subject="02"),
        "SYNTHETIC",
    )
    raises(
        "a SYNTHETIC session is refused into an existing NON-synthetic dataset",
        lambda: bids.export(syn, out, subject="02", allow_synthetic=True),
        "refusing to mix",
    )
    with tempfile.TemporaryDirectory() as o5:
        r2 = bids.export(syn, o5, subject="02", allow_synthetic=True)
        side2 = json.loads(Path(r2["header"]).with_name("sub-02_task-rest_eeg.json").read_text())
        ok("...and when allowed, the sidecar says SYNTHETIC", "SyntheticWarning" in side2)
        dd5 = json.loads((Path(o5) / "dataset_description.json").read_text())
        ok("...and so does the dataset name", dd5["Name"].startswith("SYNTHETIC"))
        ok("...and the README", (Path(o5) / "README").read_text().startswith("SYNTHETIC"))
        r3 = bids.export(syn, o5, subject="03", allow_synthetic=True)
        ok("a second synthetic export into the synthetic root is fine", r3["synthetic"])
        raises(
            "...but a real recording is refused into a SYNTHETIC dataset",
            lambda: bids.export(st, o5, subject="04"),
            "refusing to mix",
        )

    # Stream integrity counted by the bridge travels with the session into the export.
    D.annotate(
        {"stamp": st60, "stream_parse_errors": 2, "stream_gaps": 1, "stream_max_gap_us": 12000}
    )
    with tempfile.TemporaryDirectory() as o6:
        r6 = bids.export(st60, o6, subject="01")
        s6 = json.loads(Path(r6["header"]).with_suffix(".json").read_text())
        ok(
            "gaps and malformed lines the bridge counted are in the sidecar",
            s6.get("StreamIntegrity", {}).get("Gaps") == 1
            and s6["StreamIntegrity"]["ParseErrors"] == 2,
        )

    # --------------------------------------------------- independent read-back with MNE --
    try:
        import mne
        import mne_bids
    except ImportError:
        S.append("MNE-BIDS read-back -- mne/mne-bids not installed (pip install mne mne-bids)")
    else:
        mne.set_log_level("ERROR")
        raw = mne_bids.read_raw_bids(
            mne_bids.BIDSPath(subject="01", task="rest", root=out, datatype="eeg"), verbose="ERROR"
        )
        data = raw.get_data()[0] * 1e6
        vals = [512 + (i % 7) for i in range(500)]
        med = sorted(vals)[250]
        expect = [(v - med) * 7.9 for v in vals]
        ok("MNE-BIDS reads the export back at the declared rate", raw.info["sfreq"] == 250.0)
        ok(
            "...with every sample equal to (count - median) x 7.9 uV",
            len(data) == 500 and max(abs(a - b) for a, b in zip(data, expect)) < 1e-3,
        )
        ok(
            "...and the tag as an annotation at 0.4 s",
            any(abs(a["onset"] - 0.4) < 1e-6 for a in raw.annotations),
        )
        ok("...typed as the readout (EEG)", raw.get_channel_types() == ["eeg"])
        with tempfile.TemporaryDirectory() as o7:
            bids.export(ecg, o7, subject="01", task="rest")
            raw_e = mne_bids.read_raw_bids(
                mne_bids.BIDSPath(subject="01", task="rest", root=o7, datatype="eeg"),
                verbose="ERROR",
            )
            ok(
                "an ECG export reads back through MNE-BIDS typed ecg, with PowerLineFrequency n/a",
                raw_e.get_channel_types() == ["ecg"],
                str(raw_e.get_channel_types()),
            )

for s in S:
    print(f"  SKIP {s}")
for f in F:
    print(f"  FAIL {f}")
print(f"\nstorage+bids/dev_check: {len(P)}/{len(P) + len(F)} passed")
sys.exit(1 if F else 0)
