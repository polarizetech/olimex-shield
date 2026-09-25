# The extraction layer on this rig — EXPERIMENTAL

> **Status: experimental.** Everything here uses the optional companion signal-detection tool
> (found through `$OLIMEX_TOOLS`) and private captures that are not in this repo (found only through
> `$OLIMEX_RIG_CAPTURES`). Without both, `rig_noise_floor.py` exits with a message saying which is
> missing. Every µV and nV figure below inherits the rig's **7.9 µV/count, which comes from the
> shield's built-in cal signal at its nominal amplitude and is not externally verified**
> (`rig.UV_PER_COUNT_PROVENANCE`). See `docs/experimental.md`.

Part 1 of this write-up (the layer against a real human 40 Hz ASSR, OpenNeuro ds005185) lives with
the companion signal-detection tool. What stays here is about THIS board.

# Part 2 — the gate, run against this rig's own recordings

`OLIMEX_RIG_CAPTURES=… OLIMEX_TOOLS=… python3 rig_noise_floor.py`. **This is
`EXPLORATORY/RIG-CAN-DETECT-AT-ALL`, and it is no longer UNRUN.**

A private set of **eight sessions recorded on the actual Olimex rig** (not in this repo)
(Oz–Cz, mastoid ground, 250/256 Hz, ~1.5 M samples) with sidecar JSON documenting acquisition. The
script reads them and **writes nothing** — they are personal recordings and stay local. Everything
below is an aggregate statistic.

## The two unverified rig figures

| figure | was | now |
|---|---|---|
| µV per count | `~8`, RECALLED-VERIFY | **7.9, still unverified** — identical in all 8 sidecars, but every sidecar carries the same cal-derived figure (built-in cal signal, nominal amplitude). Consistency is not confirmation; no external injection has been made. The datasheet implies 1.72. |
| noise floor | `~34 µV RMS`, RECALLED-VERIFY | **the wrong quantity entirely** — see below |

## The correction that matters: a broadband RMS is not the noise a lock-in fights

`required_dwell_s()` assumes white noise and therefore takes a broadband RMS. Real EEG is
drift-dominated, and the two differ enormously:

| capture | broadband RMS | noise @40 Hz, 60 s dwell | white-noise model |
|---|---|---|---|
| capture A | 227.6 µV | **750 nV** | 2 628 nV |
| capture B | 82.4 µV | **65 nV** | 941 nV |
| capture C | 39.8 µV | **75 nV** | 460 nV |
| capture D | 502.9 µV | **238 nV** | 5 808 nV |
| capture E | 780.2 µV | **392 nV** | 8 903 nV |
| capture F | 85.7 µV | **64 nV** | 978 nV |

The white-noise model is **3.5–24× pessimistic in amplitude (median 15×) — 12–594× in dwell time.**
That error runs in the dangerous direction: it says *"unrunnable, go buy hardware"* about a
measurement that may be fine. `local_noise()` and `budget_from_record()` now measure the noise at
the frequency of interest from neighbouring bins, assuming only local smoothness in frequency.

## The answer

> **Correction — 2026-09-13.** This section previously gave the median as **238 nV** and the
> overstatement as **20–90×**. Both came from `rig_noise_floor.py` output that was wrong: the median
> indexed `sorted(floors)[n // 2]`, which on six values takes the upper-middle one, and the "90" was a
> hard-coded literal in a print statement that nothing computed. From the same six captures the
> median is **157 nV** (range 64–750, 11.7×) and the overstatement is **3.5–24× in amplitude**
> (median 15×; 12–594× in dwell). The spread was also attributed to electrode preparation; the
> session sidecars do not support that — the one capture scored good-contact (α SNR 36) has the
> highest 40 Hz figure and the one flagged as implausibly small sits mid-range — so these are in-band
> power of a scalp recording, not an instrument noise floor. No shorted-input measurement exists.
> The dwell table and the 712 nV figure are computed on one capture (the 750 nV one), not the median.

**Median in-band noise at 40 Hz after 60 s of coherent dwell: 157 nV** (range 64–750 nV, n = 6 captures).

| target | required dwell | verdict |
|---|---|---|
| 1 000 nV | 5.1 min | **RUNNABLE** |
| 300 nV | 56 min | unrunnable in a 10 min window |
| 100 nV | 507 min | unrunnable |
| 30 nV | 5 628 min | unrunnable |

**A cortical 40 Hz ASSR (hundreds of nV upward) is plausibly within reach on this rig. A
brainstem-class response — ABR, FFR, tens of nV — is about two orders of magnitude out of reach,
and no amount of processing closes that.** That is a decision, and it is the one this whole layer
was built to produce.

## Three operational facts worth more than the software

1. **The spread across sessions is 11.7×** (64 → 750 nV), larger than any algorithmic choice in
   this tool. *Corrected 2026-09-13:* this item was titled "Electrode prep dominates everything".
   The sidecars do not support that — the good-contact capture has the highest value — so the
   cause of the spread is open. Prepping electrodes well is still right; it is not shown here.
2. **Mains is 60 Hz here** and clearly present. Keep the target frequency and both sidebands off
   60 Hz and its harmonics.
3. **The sideband window at 256 Hz is 120–128 Hz**, so the widest usable Δf is ~5 Hz. Same Nyquist
   wall as before, confirmed at the rig's real rate.

## What the tri-state got right, stated accurately

`budget()` refused to give a verdict from the RECALLED floor, and that refusal earned its keep —
but not by inverting a conclusion. Had the 34 µV figure been believed, the smallest response
detectable in 10 min would have read **372 nV**; measured on the noisiest capture, it is **712 nV**. The two **agree** on
the verdict at every target tested and differ ~2× on the smallest response worth chasing. The
recalled figure was *optimistic*, not *wrong-signed*. Saying otherwise would be the same
overclaiming this document exists to avoid.

## The quality gate that matters more than the algorithm

Every dwell projection assumes noise falls as 1/√T. On these captures **that assumption holds on 5
of 9 segments and fails outright on 4**:

| session | noise 10 s → 90 s | ratio vs ideal |
|---|---|---|
| capture F | 269 → 49 nV | **1.83** — better than textbook |
| capture B | 114 → 51 nV | 0.74 |
| capture C | — | **0.49 FAIL** |
| capture E | 195 → 255 nV | **0.26 FAIL** — *worse* with more dwell |
| capture D | — | **0.10 FAIL** |

A failing session is **drift-limited, not noise-limited**: recording for longer buys nothing, and
the fix is re-prepping the electrodes, not more time. `integration_check()` makes this a one-call
check to run *before* committing to a long dwell. It is the cheapest thing in this tool and it is
worth more than every algorithmic choice in it.

## The pre-registered detection threshold

`injection_curve_from_record()` adds a known signal to **real recorded baseline noise** — including
its drift, mains and artefacts, none of which a Gaussian model contains. Restricted to sessions that
pass the integration gate (n=4):

| dwell | best | typical | worst |
|---|---|---|---|
| 10 s | 204 nV | 1014 nV | 13 278 nV |
| 30 s | 22 nV | 457 nV | 4 920 nV |
| 60 s | 27 nV | 216 nV | 3 455 nV |
| 90 s | **21 nV** | **174 nV** | **2 846 nV** |

Reported as a distribution, not a single number, because with a handful of segments the pooled
"80% of trials" figure is a worst case set by the noisiest session — and quoting either one alone
would misrepresent the rig in whichever direction happened to suit. The **~135× best-to-worst
spread is the rig**; the algorithm is not the variable.

**A bug found in this function while writing it, worth recording:** the first version bracketed each
segment's search from the *pooled* median noise, so a segment much noisier than the median failed at
the top of the bracket and was **silently dropped** — biasing the per-segment statistics optimistic
by excluding exactly the hardest cases. Each segment now brackets from its own noise, the bracket
widens rather than giving up, and anything still undetected is *counted* in
`segments_undetected_at_any_tested_amplitude`. Same "no silent caps" rule the rest of the repo runs
on, violated by its own author on first write.

These numbers were stated in a preregistration **before** any stimulus session existed, which is
the only order in which a capability claim is a limit rather than an excuse for a null.

## Still open

The rig's **noise** is characterised; the rig has never been shown to **detect** anything. None of
these sessions (six with a measurable baseline, of twelve captures) played a stimulus at a known exact frequency, so there is no numerator. The
next measurement is now well-posed and cheap: **play a 40 Hz AM stimulus, record Oz–Cz, and test the
response against the measured floor (median 157 nV).** If it lands above ~700 nV it will be visible inside ten minutes even on the noisiest session.

---

## Honest summary

The analysis chain has now recovered a real human evoked response, with correct controls, at a
frequency it was told about in advance — and the exercise immediately found a defect that would have
produced a false sustain finding. That is the whole argument for running on real data.

It validates the **analysis**, on someone else's better hardware. The cheap bench measurement of
*this* rig still has not been made, and that remains the gate.

## Provenance

Data is CC0 (Mikkelsen, Kidmose & Rezaei Tabar; `doi:10.18112/openneuro.ds005185.v1.0.0`), fetched
version-pinned at v1.0.0 with the licence re-checked live at fetch time. `validation/data/` is
gitignored — the scripts reproduce it. `numpy`/`scipy` are used only to read the EEGLAB `.set`/`.fdt`
container; every signal-processing call goes to the stdlib `extract.py` with plain Python lists, so
the tool under test gains no dependency.

**Sidenote worth keeping:** the first-choice dataset was `ds008065` (*Optimizing parameters for
multiband ABRs to continuous speech* — an actual FFR study, the closer domain match). Every one of
its S3 objects returns **HTTP 403**, including `dataset_description.json`; 25 other datasets tested
identically returned 200. That is server-side and dataset-specific. Re-check before planning around
it.
