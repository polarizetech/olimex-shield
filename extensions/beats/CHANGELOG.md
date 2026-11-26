# Changelog — olimex-shield-ext-beats

Format: [Keep a Changelog](https://keepachangelog.com/). This extension is versioned apart from
olimex-shield and declares the olimex-shield releases it was tested against (`REQUIRES`).
Everything it serves is exploratory (`scope/ecg-beats.md`).

## [0.1.0] — 2026-11-26

Tested against olimex-shield 0.3.0 (`REQUIRES = ">=0.3.0,<0.4"`).

### Added
- `GET /beats`: R peaks in the last 5 s of the live ring by Elgendi 2013's two moving averages
  (`detect.py`), each beat numbered once (`k`), with its host time `t`, `age_s` and `rr_s`.
