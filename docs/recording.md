# Recording, playback, uploads and export

## Where a session lives

A session is a folder:

```
sessions/20260915-081810-olimex-shield/
  samples.csv      sample_index,value   (raw ADC counts, one channel)
  session.json     provenance + the tag track
  uploads.json     receipts, one per upload (only after an upload)
```

The folder is `$OLIMEX_SESSIONS`, else `$BIOSIGNAL_DATASET`, else `<repo>/sessions/`. That last
one is gitignored. **Physiological data never goes in git.**

The bridge also writes its own **black box**, `apps/server/recordings/rec-*.csv`. It is written
by the process that holds the port, so it survives the browser tab crashing. Its first line
records `started_total`, and `session.json` names the black box. Checked on the real board: a
browser session is an exact, contiguous slice of its black box, starting at sample 0.

## What `session.json` says

| field | meaning |
|---|---|
| `source` | `electrode`, `synthetic` or `replay`. A synthetic session carries `synthetic_warning` and cannot lose it. |
| `readout`, `montage`, `site`, `front_end` | what was measured, where, and whether the board could carry it |
| `rate_hz` | the DECLARED sample rate. Tags and sample indices use this clock. |
| `rate_measured_hz`, `rate_error_ppm`, `rate_basis` | the bridge's host-clock measurement of the board's real rate, added after Stop by `annotate()` |
| `effective_rate_hz` | samples ÷ wall-clock seconds. Contaminated by browser throttling; kept so nobody mistakes it for a resample. |
| `electrodes_on_at` | when the operator confirmed the electrodes were on (the hookup dialog), not when Record was pressed |
| `tags` | `{label, t_s, note, wall_s}`. `t_s` is seconds since the session's first SAMPLE, never the wall clock. |
| `tag_clock_warning` | present if any tag falls outside the session's own samples |

**A tag may not carry what it is expected to do.** Keys such as `expected`, `hypothesis` or
`predicted` are refused at any depth. A record of what happened that also states the hypothesis
has put the hypothesis into the only thing the analysis is allowed to see.

## Playback

**Sessions** lists every session.

- Selecting one draws the whole record as a min/max overview (a one-sample spike survives) and a
  scrolling trace, with the tags marked on both.
- Play at 0.5–10×, jump between tags, or click the overview to seek.
- Playback uses the declared rate, because that is the clock the tags were made on.

## Uploads

Nothing uploads unless configured, and this repo has no storage client. `$OLIMEX_UPLOADER` is:

- **`none`** (default): sessions stay on this machine.
- **`module:function`**: a plugin, called as `function(session_dir, stamp, meta) -> dict`.
  `$OLIMEX_UPLOADER_PATH` is added to `sys.path` first.

Every hand-off:

1. refuses a session that is still recording or was never stopped;
2. gives the plugin a **staged copy** holding exactly the session's data files, never an earlier
   upload's receipts;
3. refuses a plugin that returns anything but a receipt;
4. keeps the receipt in `uploads.json` beside the session.

Privacy is the plugin's contract: write to a private location, never set a public ACL, and check
the upload with a request that carries no credentials.

```bash
export OLIMEX_UPLOADER=my_uploader:upload
export OLIMEX_UPLOADER_PATH=/path/to/dir/containing/my_uploader
```

## BIDS export

**Sessions → Export BIDS**, or:

```bash
python3 apps/server/bids.py <stamp> exports/bids --subject 01 --task rest
```

This writes EEG-BIDS 1.9.0 with BrainVision data files.

- **Units** are µV: (count − session median) × `uv_per_count`. The board is AC-coupled in
  silicon, so the median is ADC bias, not physiology. The scaling used is written into the
  sidecar as `Scaling`.
- **`HardwareFilters`** holds the board's 0.16–40 Hz analog band.
- **`SamplingFrequency`** is the declared rate. **`SamplingFrequencyMeasured`** is the bridge's
  measurement, when the session has one.
- **Tags** become `events.tsv` and BrainVision markers.
- **`ScalingProvenance`** says where µV per count came from (the shield's built-in cal signal, at
  its nominal amplitude, not externally checked).
- **`PowerLineFrequency`** comes from the session's `mains_hz`, else `$OLIMEX_MAINS_HZ`, else `n/a`.
- **ECG and EMG sessions** stay in the `eeg` datatype (BIDS 1.9 has none of their own) with the
  channel typed ECG or EMG and a `RecordingNote` saying so.
- **`SoftwareVersions`** carries this repo's version, which is also stamped into `session.json`.
- **`StreamIntegrity`** carries the bridge's count of malformed lines and timestamp gaps.
- A root `README` is written if there is none. `--license` and `--author` (repeatable) fill those fields.
- **Subject, session and task labels must be alphanumeric.** Nothing is derived from the session,
  so a name cannot reach a filename.
- **Synthetic sessions are refused** unless `--allow-synthetic`, and then the dataset name, README
  and sidecar all say SYNTHETIC. Synthetic and real sessions never share a dataset root.

`apps/server/dev_check_storage.py` reads an export back with MNE-BIDS and checks every sample, the
rate, the channel type and the annotation. The official `bids-validator` has not been run against
an export yet.
