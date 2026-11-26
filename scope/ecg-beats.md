# Scope: ecg-beats

Goal: with the shield on a person, the bridge reports each heartbeat's R-peak time and R-R interval live, so polarize-holo can time cues and push its grains on the real heartbeat (owner, 2026-11-26: "Let's try the olimex shield bridge and use it as a ECG for timing queues with the heart beat").

Tier: explore

Features:

F1. R-peak detection on the live ring: Elgendi's two event-related moving averages. The last 5 s of samples are band-passed 8 to 20 Hz (third-order Butterworth, run forward and backward) and squared; a 97 ms moving average (the QRS) is compared with a 611 ms one (the beat) plus an offset of 0.08 times the mean of the squared signal; a block where the first is above is a QRS when it is at least 97 ms wide, and its R peak is the largest absolute filtered value in it. The extracted passage prints the offset fraction as "0.8"; the range tested was 0 to 10 % and 2 to 10 % was optimal, so it is read as 0.08.
Source: Elgendi 2013, Fast QRS Detection with an Optimized Knowledge-Based Method: Evaluation on 11 Standard ECG Databases, DOI 10.1371/journal.pone.0073557
Evidence: W2080883481#p12.65058274 "the optimal frequency range for QRS detection in the MIT-BIH Arrhythmia Database is 8–20 Hz"
Evidence: W2080883481#p6.2fe70560 "using a third-order Butterworth filter"
Evidence: W2080883481#p22.b71c31f9 "= 35 samples 97 ms, = 220 samples 611 ms"
Evidence: W2080883481#p22.b71c31f9 "The optimal offset fraction varies from 2 to 10%"
Evidence: W2080883481#p10.eeb81ef4 "finding the maximum absolute value within each block, the R peak"
Chosen over Pan & Tompkins: Porr & Macfarlane 2024, DOI 10.1371/journal.pone.0309739, W4404230332#p34.c8849e8e "EngZee, Elgendi and the WQRS are the best detectors available".

F2. Beat events: `GET /beats` returns each beat in the window once numbered (k), with its time (`t_us`), the board-clock time from the beat to the newest sample (`behind_newest_s`) and the R-R interval from the beat before (`rr_s`). Times are the board's own t_us (owner, 2026-11-26: "Yes, board clock"). Two R peaks less than 97 ms apart (one QRS) are the same beat. Source: build. Raw: no beat is dropped or moved (owner, 2026-11-26; AGENTS.md); the steps that run are listed in extensions/beats/README.md.

Not here: electrodes and their placement (docs/hardware.md), predicting the next beat, any use of the beats (polarize-holo `scope/ecg-heart.md`). A personal rig, not a medical device; nothing it shows is a finding.
