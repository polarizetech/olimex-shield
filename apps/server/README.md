# apps/server — the bridge

The one process that holds the board's serial port, plus the checks that say whether what it reads
can be trusted. The workbench
(`apps/web`) starts it for you; run it on its own when another app wants the stream.

```bash
pip install pyserial          # optional — only the acquisition half needs it
python3 apps/server/serve.py 8140 127.0.0.1
```

**Acquisition.** Arduino + Olimex SHIELD-EKG-EMG → serial CSV → ring buffer → SSE.
**One process owns the port; every project is a client.** The flashed firmware source lives at
[`apps/olimex-shield/eeg_stream/eeg_stream.ino`](../olimex-shield/eeg_stream/eeg_stream.ino) — cross-checked against the live board
2026-09-14 (see [`../olimex-shield/README.md`](../olimex-shield/README.md) and [`RIG.md`](RIG.md)).

```html
<script src="http://localhost:8140/eeg-client.js"></script>
<script>
  const eeg = new EEGClient({ base: 'http://localhost:8140' });
  await eeg.connect();
  eeg.onData(() => eeg.scope(document.getElementById('scope')));
</script>
```

**Experimental: the Auditory Response Atlas and the extraction layer.** With the optional companion
tools installed (`$OLIMEX_TOOLS`, see [`../../docs/experimental.md`](../../docs/experimental.md)),
this process also serves experimental routes (`experimental.py`): describe what you are about to
play into each ear and get back which evoked responses should exist and where to put the
electrodes, or run a lock-in at a known frequency. Every response says `"experimental": true`.

```bash
curl -s localhost:8140/montage -H 'Content-Type: application/json' -d '{
  "stimulus": {"transducer":"insert_earphone",
    "left":{"kind":"am_tone","carrier_hz":500,"am_rate_hz":40,"level_db_spl":70},
    "right":{"kind":"am_tone","carrier_hz":500,"am_rate_hz":40,"level_db_spl":70}},
  "channels": 3 }'
```

Without the companion tools those routes answer 503 "not installed"; acquisition is unaffected.

- **Integrating either half into another project → [`INTEGRATION.md`](INTEGRATION.md)**
- Architecture, firewalls and honesty rules → [`CLAUDE.md`](CLAUDE.md)
- Self-tests: `python3 dev_check.py`

Acquisition survives browser reloads (the server owns the port), recordings survive browser/OS
crashes (server-side black box), malformed lines and dropped samples are counted from the board's
`t_us` and never repaired, and CORS allows loopback origins (plus `$OLIMEX_ALLOWED_ORIGINS`) so
local apps on other ports can consume it. The atlas **predicts and measures nothing** — its scalp
maps are a forward model from published anatomy, never source localisation.
