"""rig.py -- what the hardware on this desk actually is, as numbers other code can import.

STDLIB ONLY. Pure constants and one first-order response model; no device, no writes, and
nothing here may import anything else from this tool (`dev_check.py` asserts it), so a
client can read the rig's parameters without pulling in the acquisition daemon.

WHY IT LIVES HERE: the bridge holds the serial port as an exclusive resource, and the device's
parameters belong beside the process that owns the device. Each number below says where it came
from: MEASURED on the real board (RIG.md), NOMINAL (a manufacturer figure), or a configuration.

*** THE FACT MOST CLIENTS GET WRONG. ***
The 0.16 Hz high-pass and the 40 Hz low-pass are in SILICON, ahead of the converter. No
sample rate, no dwell, no averaging and no filter choice recovers anything they removed.
`carries()` exists so a client asks that question before a session rather than after one.

The rig noise figures in nV (MEASURED_RIG, NOISE_NV_AT_40HZ) and the RECALLED table are
EXPERIMENTAL and live in `experimental.py`, beside the routes that use them.

KNOWN DUPLICATION, recorded rather than hidden: an earlier internal client holds its own
copies of FRONT_END_HP_HZ / FRONT_END_LP_HZ / UV_PER_COUNT / NOMINAL_RATE_HZ and a richer
channel model (3rd-order Besselworth low-pass, target catalogue). It predates this file, and
until it imports these the two can drift.
"""

import math
import os

PORT_HINT = "/dev/cu.usbmodem*"
BAUD = 115200  # MEASURED. Not 57600 -- the OpenEEG guess cost the first probe.
# 250.0 is what the board's OWN clock says (t_us steps of 4000), and that is circular: the board's
# clock is the thing in question. Against the host clock the same board ran at -644 ppm one
# morning and -685 ppm that afternoon (RIG.md, 2026-09-15) -- it DRIFTS, so no constant here can
# be the measured rate. Kept at 250 because every consumer's arithmetic assumes it. Anything doing
# LOCK-IN detection must use the bridge's live measurement instead: `/status` -> `rateMeasured`
# (apps/server/timebase.py). At -644 ppm a 60 Hz lock-in nulls a 40 dB line within 40 s.
NOMINAL_RATE_HZ = 250.0
#: A SNAPSHOT, not a value to use: the first host-clock measurement (123 s, 2026-09-15 AM). It was
#: 41 ppm out of date within hours. Kept only so the magnitude is on record next to the constant.
RATE_ERROR_PPM_SNAPSHOT = -644
ADC_BITS = 10
ADC_MIN, ADC_MAX = 0.0, 1023.0
ADC_MID = 511.5

#: NOT EXTERNALLY VERIFIED. 7.9 uV/count was derived in an earlier internal app from the shield's
#: BUILT-IN calibration square wave: its nominal ~250 uV peak-to-peak read as ~31.6 counts, and
#: 250 / 31.6 = 7.9. The cal amplitude is the manufacturer's NOMINAL figure; nobody has checked it
#: (or this scale) with an externally injected signal of known amplitude. The same 7.9 appears in
#: every sidecar that app wrote, which is consistency, not confirmation. The datasheet gain implies
#: 1.72; the 4.6x disagreement is DECLARED, not resolved -- it decides whether 5 uV is 0.6 or 2.9
#: counts. Every microvolt figure in this repo inherits this uncertainty.
UV_PER_COUNT = 7.9
UV_PER_COUNT_PROVENANCE = (
    "from the shield's built-in cal signal, nominal amplitude (~250 uV p-p read as ~31.6 counts); "
    "not externally verified. The datasheet gain implies 1.72 uV/count."
)
UV_PER_COUNT_DATASHEET = 1.72

FRONT_END_HP_HZ = 0.16  # first-order input high-pass, in silicon, BEFORE the ADC
FRONT_END_LP_HZ = 40.0  # low-pass, also before the ADC
HP_TAU_S = 1.0 / (2.0 * math.pi * FRONT_END_HP_HZ)  # 0.9947 s

#: The BENCH's mains frequency (this desk is on a 60 Hz grid; RIG.md measured 60 Hz at +32.2 dB).
#: A default for the contact check only when nothing better is configured -- never written into an
#: export as if it were a fact about someone else's recording. See `configured_mains_hz()`.
MAINS_HZ = 60.0
MAINS_ENV = "OLIMEX_MAINS_HZ"


def configured_mains_hz():
    """The mains frequency from `$OLIMEX_MAINS_HZ`, or None when it is unset or not a number.

    None is an answer: the BIDS export then writes "n/a", and the contact check falls back to the
    bench default (MAINS_HZ) and says so in its `mains_hz_basis`.
    """
    v = os.environ.get(MAINS_ENV)
    try:
        f = float(v) if v not in (None, "") else None
    except ValueError:
        return None
    return f if f and f > 0 else None


SOURCE = "apps/server/RIG.md -- MEASURED on this board unless a constant says otherwise"


def highpass_gain(f_hz: float) -> float:
    """First-order high-pass magnitude. A MODEL of the real board, never measured on it."""
    if f_hz <= 0:
        return 0.0
    r = f_hz / FRONT_END_HP_HZ
    return r / math.sqrt(1.0 + r * r)


def lowpass_gain(f_hz: float) -> float:
    """First order, deliberately conservative: the real board is higher order, so this
    UNDERSTATES the attenuation above the corner. Do not quote it as the board's response."""
    r = f_hz / FRONT_END_LP_HZ
    return 1.0 / math.sqrt(1.0 + r * r)


def channel_gain(f_hz: float) -> float:
    return highpass_gain(f_hz) * lowpass_gain(f_hz)


def db(ratio: float) -> float:
    return -999.0 if ratio <= 0 else 20.0 * math.log10(ratio)


def characteristic_hz(duration_s: float) -> float:
    """The frequency a feature lasting `duration_s` puts most of its energy at."""
    return 1.0 / (2.0 * float(duration_s)) if duration_s > 0 else float("inf")


#: Below this gain the front end has taken more than 90% of the amplitude. A `convention`,
#: chosen so that "unreachable" means an order of magnitude, not a rounding error.
UNREACHABLE_GAIN = 0.1
DEGRADED_GAIN = 0.7


def carries(f_hz: float) -> dict:
    """Can this front end carry a signal whose energy is at `f_hz`? Gain, dB, and a verdict.

    The verdict is `reachable` / `degraded` / `unreachable`, and `unreachable` is a claim
    about the SILICON: a session run against it will produce a clean-looking null that says
    nothing about the world.
    """
    g = channel_gain(f_hz)
    v = "unreachable" if g < UNREACHABLE_GAIN else "degraded" if g < DEGRADED_GAIN else "reachable"
    return {
        "f_hz": float(f_hz),
        "gain": g,
        "db": db(g),
        "verdict": v,
        "hp_hz": FRONT_END_HP_HZ,
        "lp_hz": FRONT_END_LP_HZ,
        "source": SOURCE,
        "note": (
            "the corners are analog and ahead of the converter; nothing downstream "
            "recovers what they removed"
        ),
    }
