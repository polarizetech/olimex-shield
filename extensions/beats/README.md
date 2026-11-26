# extensions/beats

`GET /beats`: heartbeats from the live ECG, as R-peak times and R-R intervals, by Elgendi 2013's detector (doi:10.1371/journal.pone.0073557). Exploratory (`scope/ecg-beats.md`); a personal rig, not a medical device.

## Beats are raw (owner, 2026-11-26)

No beat is dropped and no beat's time is moved (`AGENTS.md`, "Beats are reported raw"). The raw signal itself is the bridge's: record it with `POST /record` for the whole session (`apps/server/INTEGRATION.md`), and correct anything afterwards, from that recording.

## Every processing step that runs

On each request, on the last 5 s of the live ring (`?seconds=` changes it):

- **The detector's own signal.** The samples are band-passed 8 to 20 Hz (third-order Butterworth, run forward and backward, so no shift in time) after subtracting their mean, and squared. This copy only finds the beats; the samples the bridge streams and records are untouched.
- **What counts as a beat (Elgendi 2013).** A 97 ms moving average is compared with a 611 ms one plus 0.08 times the mean of the squared signal; a stretch where the first is above is a beat when it is at least 97 ms wide, and its R peak is the sample with the largest absolute filtered value in it. This is the method's definition of a beat, not a filter on beats found.
- **Not finished yet.** A stretch still open at the newest sample is not reported until a later request, when it has closed.
- **The time.** A beat's time `t` is the host clock: the time of the request minus the R peak's distance from the newest sample, at the bridge's rate. It assumes the newest sample arrived at the moment of the request, so it carries the serial link's delay.
- **One beat, one number.** A beat found again by a later request (within 97 ms, one QRS, of a beat already numbered) keeps its first number `k` and its first time `t`; the later estimate is not reported.
- **R-R.** `rr_s` is the time from the beat numbered just before it, when that one is earlier; otherwise null.

Nothing else: no smoothing, no R-R limits, no refractory period, no confirmation, no gap filling.
