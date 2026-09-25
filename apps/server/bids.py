"""bids.py -- export a finished session as a BIDS dataset (EEG-BIDS, BrainVision data files).

Stdlib only: the BrainVision format is a text header, a text marker file and a raw float32
file, so writing it needs nothing. Reading it back needs MNE, which is how `dev_check_bids.py`
verifies an export -- an independent reader, not this module's own opinion of its output.

    python3 bids.py <stamp> <out_dir> --subject 01 --task rest

What goes where:

    <out>/dataset_description.json
    <out>/README                            written once if the root has none
    <out>/participants.tsv                  participant_id only. No names, ever.
    <out>/sub-01/[ses-x/]eeg/sub-01_[ses-x_]task-rest_eeg.{vhdr,vmrk,eeg,json}
                                            ..._channels.tsv, ..._events.tsv (the tag track)

*** WHAT THE EXPORT SAYS THAT THE RAW SESSION DID NOT. ***

  * UNITS. Sessions store raw ADC counts. The export is microvolts: the session's median is
    subtracted (the board is AC-coupled at 0.16 Hz in silicon, so the ADC's resting code is
    bias, not physiology) and the result is multiplied by the session's `uv_per_count`, or by
    `rig.UV_PER_COUNT` (7.9, from the shield's built-in cal signal at its NOMINAL amplitude, not
    externally verified) when the session did not record one. Which was used, and that
    provenance, are written into the sidecar (`Scaling`, `ScalingProvenance`). The Olimex
    datasheet implies 1.72; that 4.6x disagreement is carried, not resolved.
  * MAINS. `PowerLineFrequency` is the session's `mains_hz`, else `$OLIMEX_MAINS_HZ`, else "n/a"
    (BIDS 1.9 allows "n/a"). It is never assumed from the bench this code was written on.
  * VERSION. `SoftwareVersions` names the chain version (pyproject.toml) that exported it, and
    the one that recorded it when the session says.
  * ECG / EMG. BIDS 1.9 has no standalone ECG or EMG datatype, and EEG-BIDS lists ECG and EMG
    as valid channel types inside an `eeg` recording. So a non-EEG session is exported as the
    `eeg` datatype with its channel typed ECG/EMG, EEGChannelCount 0, the matching
    ECGChannelCount/EMGChannelCount 1, and a `RecordingNote` saying so.
  * FILTERS. The 0.16-40 Hz band is in the board's hardware and goes into `HardwareFilters`.
  * RATE. `SamplingFrequency` is the DECLARED grid (what the firmware schedules). The board's
    real rate differs by ~680 ppm and drifts; the bridge measures it (`timebase.py`) and, when
    the session recorded that measurement, it is written as `SamplingFrequencyMeasured`.

*** WHAT IT REFUSES. ***

  * a synthetic session, unless `allow_synthetic=True` -- a BIDS dataset is exactly the thing
    that gets passed on without its context, and generated data must not leave wearing the
    look of a recording. When allowed, the sidecar and the dataset name both say SYNTHETIC;
  * MIXING: a synthetic session into a dataset whose name does not say SYNTHETIC, or a
    recording into one that does. The dataset name is the one label that travels with every
    file in it, so the two never share a root;
  * a subject, session or task label that is not alphanumeric (BIDS entity rule) -- and it
    never derives one from anything in the session, so a name cannot leak into a filename;
  * a session still recording, or with no samples.
"""

from __future__ import annotations

import csv
import json
import re
import statistics
import struct
import sys
from pathlib import Path

import rig
import sessions

BIDS_VERSION = "1.9.0"
TYPES = {"eeg": "EEG", "ecg": "ECG", "emg": "EMG"}
SYNTHETIC_PREFIX = "SYNTHETIC — "
_READMES = ("README", "README.md", "README.rst", "README.txt")


def _mains_for(meta):
    """PowerLineFrequency: the session's, else $OLIMEX_MAINS_HZ, else "n/a" -- never assumed."""
    v = meta.get("mains_hz")
    if v:
        return float(v)
    env = rig.configured_mains_hz()
    return env if env is not None else "n/a"


def _root_is_synthetic(dd: Path):
    """True/False for an existing dataset_description.json, None when there is none."""
    if not dd.exists():
        return None
    try:
        name = str(json.loads(dd.read_text()).get("Name", ""))
    except (OSError, ValueError):
        raise ExportError(f"{dd} exists but is not readable JSON; refusing to add to it") from None
    return name.startswith("SYNTHETIC")


class ExportError(ValueError):
    pass


def _label(kind: str, v: str) -> str:
    v = str(v or "")
    if not re.fullmatch(r"[A-Za-z0-9]+", v):
        raise ExportError(f"BIDS {kind} label must be alphanumeric, not {v!r}")
    return v


def _values(d: Path) -> list[float]:
    out = []
    with open(d / "samples.csv") as fh:
        r = csv.reader(fh)
        next(r, None)
        for row in r:
            try:
                out.append(float(row[1]))
            except (IndexError, ValueError):
                continue
    return out


def export(
    stamp: str,
    out_root,
    *,
    subject: str = "01",
    session: str | None = None,
    task: str = "rest",
    allow_synthetic: bool = False,
    license: str | None = None,
    authors: list | None = None,
) -> dict:
    """Export one finished session. `license` and `authors` go into dataset_description.json only
    when supplied (and only when this call creates it) -- they are never derived from a session,
    so nobody's name reaches a dataset by default."""
    d = sessions.session_dir(stamp)
    if not (d / "session.json").is_file():
        raise ExportError(f"no session {stamp!r}")
    if stamp in sessions._OPEN:
        raise ExportError(f"{stamp!r} is still recording")
    meta = json.loads((d / "session.json").read_text())
    synthetic = meta.get("source") == "synthetic"
    if synthetic and not allow_synthetic:
        raise ExportError(
            f"{stamp!r} is SYNTHETIC. Refusing to export it as a BIDS recording; "
            "pass allow_synthetic=True if you really mean to, and it will say so."
        )
    out_root = Path(out_root)
    dd = out_root / "dataset_description.json"
    root_synthetic = _root_is_synthetic(dd)
    if root_synthetic is not None and root_synthetic != synthetic:
        raise ExportError(
            f"refusing to mix: {stamp!r} is {'SYNTHETIC' if synthetic else 'a recording'} but "
            f"the dataset at {out_root} is {'SYNTHETIC' if root_synthetic else 'not synthetic'}. "
            "Export it to a separate root."
        )
    sub, task = _label("subject", subject), _label("task", task)
    ses = _label("session", session) if session else None

    raw = _values(d)
    if not raw:
        raise ExportError(f"{stamp!r} has no samples")
    if meta.get("already_uv"):
        uv, scale_basis, offset = raw, "samples were already microvolts", 0.0
    else:
        upc = meta.get("uv_per_count")
        scale = float(upc) if upc else rig.UV_PER_COUNT
        scale_basis = (
            f"session uv_per_count = {scale}"
            if upc
            else f"rig.UV_PER_COUNT = {rig.UV_PER_COUNT} ({rig.UV_PER_COUNT_PROVENANCE})"
        )
        offset = statistics.median(raw)
        uv = [(x - offset) * scale for x in raw]

    rate = float(meta.get("rate_hz") or rig.NOMINAL_RATE_HZ)
    readout = (meta.get("readout") or "eeg").lower()
    # ECG/EMG: kept in the eeg datatype rather than refused. BIDS 1.9 has no standalone ECG/EMG
    # datatype (physio files are for recordings that accompany another datatype), EEG-BIDS lists
    # ECG and EMG as channel types an eeg recording may hold, and EEGChannelCount's minimum is 0.
    # So the channel is typed truthfully, the matching *ChannelCount is 1, and RecordingNote and
    # the README say what it is -- which is more compliant than refusing, and more honest than
    # typing a limb lead as EEG.
    ch_type = TYPES.get(readout, "MISC")
    ch_name = f"{ch_type}1"
    ents = f"sub-{sub}" + (f"_ses-{ses}" if ses else "") + f"_task-{task}"
    ddir = out_root / f"sub-{sub}" / (f"ses-{ses}" if ses else "") / "eeg"
    ddir.mkdir(parents=True, exist_ok=True)
    base = ddir / f"{ents}_eeg"

    # --- BrainVision: float32 little-endian, multiplexed, one channel, in µV
    with open(base.with_suffix(".eeg"), "wb") as fh:
        fh.write(struct.pack(f"<{len(uv)}f", *uv))
    vhdr = (
        "Brain Vision Data Exchange Header File Version 1.0\n"
        f"; Written by olimex-shield bids.py from session {stamp}\n\n"
        "[Common Infos]\nCodepage=UTF-8\n"
        f"DataFile={base.name}.eeg\nMarkerFile={base.name}.vmrk\n"
        "DataFormat=BINARY\nDataOrientation=MULTIPLEXED\nNumberOfChannels=1\n"
        f"SamplingInterval={1e6 / rate:.6f}\n\n"
        "[Binary Infos]\nBinaryFormat=IEEE_FLOAT_32\n\n"
        "[Channel Infos]\n"
        f"Ch1={ch_name},,1,µV\n"
    )
    base.with_suffix(".vhdr").write_text(vhdr, encoding="utf-8")
    tags = meta.get("tags") or []
    marks = [
        "Brain Vision Data Exchange Marker File, Version 1.0\n",
        "[Common Infos]\nCodepage=UTF-8\n",
        f"DataFile={base.name}.eeg\n\n",
        "[Marker Infos]\n",
        "Mk1=New Segment,,1,1,0\n",
    ]
    for i, t in enumerate(tags, start=2):
        label = str(t.get("label", "")).replace(",", r"\1")
        marks.append(f"Mk{i}=Comment,{label},{int(round(float(t['t_s']) * rate)) + 1},1,0\n")
    base.with_suffix(".vmrk").write_text("".join(marks), encoding="utf-8")

    # --- sidecars
    n = len(uv)
    version = sessions.software_version()
    recorded_with = meta.get("software_version")
    sw = f"olimex-shield {version} (export); firmware apps/olimex-shield/eeg_stream/eeg_stream.ino"
    if recorded_with and recorded_with != version:
        sw += f"; recorded with olimex-shield {recorded_with}"
    elif not recorded_with:
        sw += "; recording version not stored in the session"
    side = {
        "TaskName": task,
        "SamplingFrequency": rate,
        "PowerLineFrequency": _mains_for(meta),
        "SoftwareFilters": "n/a",
        "HardwareFilters": {
            "Olimex SHIELD-EKG-EMG analog front end": {
                "HighpassHz": rig.FRONT_END_HP_HZ,
                "LowpassHz": rig.FRONT_END_LP_HZ,
            }
        },
        "EEGReference": next(
            (m.get("site") for m in (meta.get("montage") or []) if m.get("role") == "reference"),
            "n/a",
        ),
        "EEGGround": next(
            (m.get("site") for m in (meta.get("montage") or []) if m.get("role") == "ground"), "n/a"
        ),
        "EEGChannelCount": 1 if ch_type == "EEG" else 0,
        "ECGChannelCount": 1 if ch_type == "ECG" else 0,
        "EMGChannelCount": 1 if ch_type == "EMG" else 0,
        "MiscChannelCount": 1 if ch_type == "MISC" else 0,
        "RecordingDuration": round(n / rate, 3),
        "RecordingType": "continuous",
        "Manufacturer": "Olimex",
        "ManufacturersModelName": "SHIELD-EKG-EMG on Arduino UNO",
        "SoftwareVersions": sw,
        "InstitutionName": "n/a",
        "Scaling": scale_basis,
        "ScalingProvenance": (
            rig.UV_PER_COUNT_PROVENANCE
            if not meta.get("already_uv") and not meta.get("uv_per_count")
            else "supplied by the session; not checked by this export"
        ),
        "DCOffsetRemoved": offset,
        "NotAMedicalDevice": "Hobby amplifier. Nothing in this recording is a diagnosis.",
    }
    if meta.get("rate_measured_hz"):
        side["SamplingFrequencyMeasured"] = meta["rate_measured_hz"]
        side["SamplingFrequencyMeasuredBasis"] = meta.get("rate_basis")
    if ch_type in ("ECG", "EMG", "MISC"):
        side["RecordingNote"] = (
            f"This is a {ch_type} recording, not EEG. BIDS {BIDS_VERSION} has no standalone "
            f"{ch_type} datatype, so it is stored in the eeg datatype with its one channel typed "
            f"{ch_type} (EEGChannelCount 0), as EEG-BIDS permits."
        )
    if meta.get("stream_gaps") is not None or meta.get("stream_parse_errors") is not None:
        side["StreamIntegrity"] = {
            "ParseErrors": meta.get("stream_parse_errors"),
            "Gaps": meta.get("stream_gaps"),
            "MaxGapMicroseconds": meta.get("stream_max_gap_us"),
            "Note": "counted from the board's t_us while the bridge recorded; no sample was "
            "inserted or repaired",
        }
    if synthetic:
        side["SyntheticWarning"] = meta.get("synthetic_warning") or "SYNTHETIC"
    (base.parent / f"{ents}_eeg.json").write_text(json.dumps(side, indent=2, ensure_ascii=False))
    (base.parent / f"{ents}_channels.tsv").write_text(
        "name\ttype\tunits\tlow_cutoff\thigh_cutoff\tstatus\n"
        f"{ch_name}\t{ch_type}\tµV\t{rig.FRONT_END_HP_HZ}\t{rig.FRONT_END_LP_HZ}\tgood\n",
        encoding="utf-8",
    )
    ev = ["onset\tduration\ttrial_type\tsample"]
    for t in tags:
        lab = str(t.get("label", "")).replace("\t", " ").replace("\n", " ") or "n/a"
        ev.append(f"{float(t['t_s']):.4f}\t0\t{lab}\t{int(round(float(t['t_s']) * rate))}")
    (base.parent / f"{ents}_events.tsv").write_text("\n".join(ev) + "\n", encoding="utf-8")

    if root_synthetic is None:
        desc = {
            "Name": (SYNTHETIC_PREFIX if synthetic else "") + "olimex-shield export",
            "BIDSVersion": BIDS_VERSION,
            "DatasetType": "raw",
            "GeneratedBy": [
                {
                    "Name": "olimex-shield",
                    "Version": version,
                    "Description": "apps/server/bids.py",
                }
            ],
        }
        # RECOMMENDED fields, written only when the caller supplies them: a License string and an
        # Authors list are both spec-valid, and a made-up one would be worse than none.
        if license:
            desc["License"] = str(license)
        if authors:
            desc["Authors"] = [str(a) for a in authors]
        dd.write_text(json.dumps(desc, indent=2, ensure_ascii=False), encoding="utf-8")
    if not any((out_root / r).exists() for r in _READMES):
        (out_root / "README").write_text(_readme(synthetic, version), encoding="utf-8")
    pt = out_root / "participants.tsv"
    rows = pt.read_text().splitlines() if pt.exists() else ["participant_id"]
    if f"sub-{sub}" not in rows:
        rows.append(f"sub-{sub}")
    pt.write_text("\n".join(rows) + "\n")
    return {
        "stamp": stamp,
        "root": str(out_root),
        "header": str(base.with_suffix(".vhdr")),
        "n_samples": n,
        "rate_hz": rate,
        "events": len(tags),
        "channel_type": ch_type,
        "scaling": scale_basis,
        "synthetic": synthetic,
    }


def _readme(synthetic: bool, version: str) -> str:
    lines = [
        ("SYNTHETIC DATA. " if synthetic else "")
        + "BIDS export written by olimex-shield "
        + version
        + " (apps/server/bids.py).",
        "",
        "Hardware: Arduino + Olimex SHIELD-EKG-EMG, one differential channel, 10-bit ADC, "
        f"declared {rig.NOMINAL_RATE_HZ:g} Hz, analog band {rig.FRONT_END_HP_HZ}-"
        f"{rig.FRONT_END_LP_HZ:g} Hz ahead of the converter. A hobby amplifier, not a medical "
        "device.",
        "",
        "Scaling: samples are microvolts computed from ADC counts. Unless a sidecar says otherwise "
        f"the scale is {rig.UV_PER_COUNT} uV/count, {rig.UV_PER_COUNT_PROVENANCE}",
        "",
        "ECG and EMG recordings, if any, are stored in the eeg datatype with their channel typed "
        "ECG or EMG; see each sidecar's RecordingNote.",
        "",
        "Sample rate: SamplingFrequency is the DECLARED rate; SamplingFrequencyMeasured, when "
        "present, is the host-clock measurement.",
    ]
    if synthetic:
        lines += ["", "Nothing in this dataset came off an electrode."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("stamp")
    ap.add_argument("out")
    ap.add_argument("--subject", default="01")
    ap.add_argument("--session")
    ap.add_argument("--task", default="rest")
    ap.add_argument("--allow-synthetic", action="store_true")
    ap.add_argument("--license", help="dataset licence, e.g. CC0 (omitted when not given)")
    ap.add_argument("--author", action="append", help="dataset author (repeatable)")
    a = ap.parse_args()
    try:
        print(
            json.dumps(
                export(
                    a.stamp,
                    a.out,
                    subject=a.subject,
                    session=a.session,
                    task=a.task,
                    allow_synthetic=a.allow_synthetic,
                    license=a.license,
                    authors=a.author,
                ),
                indent=2,
            )
        )
    except (ExportError, sessions.DatasetError) as e:
        sys.exit(f"refused: {e}")
