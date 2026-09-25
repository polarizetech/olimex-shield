# DURABILITY.md — never lose a session, and never let a partial one look complete

**This applies to every rig consumer** — anything recording from the Olimex SHIELD-EKG-EMG or any
future device, and whatever comes next. It is not one app's concern.

## The invariant

> **Any code that creates or changes a session type MUST stream the raw timeseries and all derived
> snapshots to disk AS THEY ARE CAPTURED — never buffered for a single end-of-session write.**
>
> **A clean-looking empty record is a worse outcome than an explicitly-flagged partial one.**

Promoted here from an earlier internal app's architecture notes, where it was written after a real
incident: a committed session with metadata, null measurement arrays and no
raw file — a run that looked finished and contained nothing. Everything below exists to make that
specific outcome impossible.

## The four layers, and what each one survives

| | Layer | Lives in | Survives | Dies with |
|---|---|---|---|---|
| **L1** | Daemon ring buffer + black-box CSV (`/record`) | the bridge process | browser crash, tab close, page reload, HMR | the bridge process |
| **L2** | Incremental session write (`durability.py`) | the bridge process | same as L1, and keeps **structure**, not just samples | the bridge process, the disk |
| **L3** | Browser IndexedDB failsafe (`session-recorder.js`) | the browser | **the bridge dying**, network loss, a full disk, L2 failing | clearing site data |
| **L4** | `beforeunload` confirm + `sendBeacon` | the browser | the operator closing the tab by accident | a hard kill |

**L2 and L3 are not redundant — they fail in opposite directions.** L2 survives the browser dying;
L3 survives the server dying. A session loses data only if both go at once, which is a power cut.

## The rules that make it work

1. **`terminated_early` is written TRUE at init** and only ever cleared by an explicit `finalize`.
   Every failure mode — including ones nobody anticipated — therefore leaves a record that is
   honest about being incomplete. This is the single most important line in the module.
2. **Writes are atomic** (temp file + `os.replace`). A kill mid-write leaves the previous good
   record, never a half-written one.
3. **`has_raw_samples` is recorded separately from row count**, so a reviewer can tell
   **electrode dropout** (rows present, then flat) from a **write failure** (no rows at all).
   Those need completely different fixes and look identical in any summary that only says
   "session incomplete". `list_orphans()` states which it thinks it is.
4. **The failsafe never throws.** Every L3 write is fire-and-forget and swallows its own errors.
   A durability layer that breaks a live session has destroyed the thing it protects.
5. **A server write failure downgrades to failsafe-only; it never aborts the session.**
   `SessionRecorder.serverOk` goes false and the UI should say so — loudly — but recording
   continues.
6. **Nothing is auto-deleted.** Orphans are surfaced, never cleaned up. The operator decides
   whether a partial session is usable; deleting it automatically would be this module doing the
   exact thing it exists to prevent.
7. **Run the disk self-test before a long session.** A full disk or a read-only mount produces a
   session that looks like it is recording and is not. Discovering that after 60 minutes is the
   expensive way to find out.

## Wiring a project in

```html
<script type="module">
  import { SessionRecorder } from '/bridge/session-recorder.js';   // or http://localhost:8140/…

  const rec = new SessionRecorder({ app: 'my-project', name: 'session-01' });

  const pre = await rec.preflight();          // L2 disk self-test — CHECK THIS
  if (!pre.ok) { /* warn loudly; the operator decides whether to continue */ }

  await rec.start({ csvHeader: 'sample_index,uv', meta: { subject, montage, uv_per_count } });

  // …as each window lands, not at the end:
  await rec.update(record, csvRows, 'block-3');

  await rec.finish(record);                    // the ONLY thing that clears terminated_early
</script>
```

On load, before anything else:

```js
const { server, browser } = await rec.orphans();
// Surface both lists. `downloadRecovered()` exports a browser orphan as JSON.
```

## Where the files land

`apps/server/recordings/<app>/<session>/` — `session.json` + `raw.csv`. **Gitignored;
physiological data stays local.** Path components are sanitised, never joined raw, because the
browser supplies them.

The bridge owns this directory rather than each project owning its own, for the same reason it owns
the serial port: it is the process that survives the browser, and one durable location is one place
to look after a crash. A project may of course keep its own copy as well.

## Tested against real failures, both directions (2026-08-18)

The invariant's own step 4 asks for a mid-session kill test. It had never been run — not here, and
not in the app this was ported from. It has now been run, in both directions, with the failure
actually injected rather than simulated in a unit test:

| Failure injected | Result |
|---|---|
| **Session abandoned mid-run** (no `finish()` ever called) | Server left `session.json` with `terminated_early: true`, `phase: "block-3"`, `has_raw_samples: true`, and a complete `raw.csv`. Listed as an orphan, diagnosed "interrupted; reviewable up to the last update". |
| **Bridge process killed mid-session** | Recording continued. `serverOk` flipped false on the first write and stayed false; all 8 rows were held by the browser failsafe and exported intact. |
| **Bridge restarted mid-session** | The writer **re-attached** rather than refusing, with `phase: "reattached"`, and continued writing. |

### The gap that test exposed, and it matters

**After a server death, the server-side CSV is missing every row written while it was down.** The
reattached writer only counts what it wrote itself, so `raw_rows` on disk is honest but INCOMPLETE.
In the test the server file held 2 rows and the browser failsafe held the other 8.

So: **when `phase` is `reattached`, or when the UI showed `DISK FAILING` at any point, the server
CSV is not the whole session** — export the browser failsafe and merge. The `reattached` phase
label exists to make that visible; without it, a short-but-clean-looking CSV is exactly the
"clean-looking record that is missing data" this document exists to prevent, one level up.

## What is still NOT covered

- **A power cut takes L2 and L3 together.** Nothing here is a UPS.
- **`sendBeacon` is best-effort.** It is not guaranteed on a force-quit.
- **The merge after a reattach is manual.** Nothing automatically reconciles the browser failsafe
  against the server CSV; the operator does it. Automating it is the obvious next step.
- **None of this validates the SIGNAL.** A perfectly durable recording of a disconnected electrode
  is still a recording of nothing — that is `quality.assess`'s job, and the baseline step's.
- **None of it has run against the real Olimex rig**, because no device has been attached yet. The
  failure modes tested above are process- and browser-level, which is where they belong, but a
  serial dropout mid-session is a fourth failure mode and it has not been exercised on hardware.
  Since 2026-09-25 it is at least **counted**: the bridge reads the board's `t_us` and reports gaps
  and malformed lines (`/status` → `streamGaps`, `parseErrors`; `/record/stop` → `recGaps`,
  `recParseErrors`). Nothing fills a gap; a counted hole is honest, a filled one is not.
