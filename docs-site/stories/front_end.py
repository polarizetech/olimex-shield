"""Stories for the front-end model (rig.py) and the readout catalogue (readouts.py)."""

import math

from autodocsite.story import line, story, table, verdicts, view


@story(
    id="what-the-front-end-carries",
    title="What can this front end carry?",
    page="bridge-api",
    calls=("rig.carries", "rig.channel_gain"),
    badge="MODELLED",
    summary="The shield band-limits the signal in analog hardware, before the converter. "
    "`rig.carries` answers, for any frequency, whether a feature there survives. "
    "The corners are a model of the board, so this output is modelled, not measured.",
)
def what_the_front_end_carries():
    import rig

    features = {
        "slow drift": 0.05,
        "alpha rhythm": 10.0,
        "mains": 60.0,
        "brainstem response": 1000.0,
    }
    answers = {name: rig.carries(f_hz) for name, f_hz in features.items()}

    freqs = [10 ** (k / 40) for k in range(-80, 141)]  # 0.01 Hz to ~3 kHz
    gain_db = [rig.db(rig.channel_gain(f)) for f in freqs]
    return view(
        output=[
            verdicts(
                "rig.carries(f_hz)",
                [
                    {
                        "key": name,
                        "verdict": a["verdict"],
                        "meta": f"{a['f_hz']:g} Hz",
                        "reason": f"gain {a['gain']:.3f} ({a['db']:+.1f} dB)",
                        "tone": "yes"
                        if a["verdict"] == "reachable"
                        else "no"
                        if a["verdict"] == "unreachable"
                        else "none",
                    }
                    for name, a in answers.items()
                ],
                caption=answers["alpha rhythm"]["note"],
            ),
            line(
                "rig.channel_gain(f), modelled",
                [math.log10(f) for f in freqs],
                gain_db,
                xlabel="log10 frequency (Hz)",
                ylabel="gain (dB)",
                yunit="dB",
                markers=[
                    {
                        "x": math.log10(answers["alpha rhythm"]["hp_hz"]),
                        "label": "high-pass 0.16 Hz",
                    },
                    {"x": math.log10(answers["alpha rhythm"]["lp_hz"]), "label": "low-pass 40 Hz"},
                ],
            ),
        ],
        facts=[
            (
                "band",
                f"{answers['alpha rhythm']['hp_hz']:g}–{answers['alpha rhythm']['lp_hz']:g} Hz",
            ),
            ("at 10 Hz", f"{answers['alpha rhythm']['db']:+.1f} dB"),
            ("at 1 kHz", f"{answers['brainstem response']['db']:+.1f} dB"),
        ],
        raw=answers,
    )


@story(
    id="readout-gates",
    title="Which readouts can it carry at all?",
    page="workbench-api",
    calls=("readouts.catalogue", "readouts.gate"),
    badge="MODELLED",
    summary="Each readout in the catalogue names the feature that makes it informative. "
    "`readouts.gate` asks the front-end model whether that feature fits in the band, "
    "and answers before anything is recorded.",
)
def readout_gates():
    import readouts

    gates = {r["key"]: readouts.gate(r["key"]) for r in readouts.catalogue()}

    return view(
        output=[
            verdicts(
                "readouts.gate(key)['overall']",
                [
                    {
                        "key": key,
                        "verdict": g["overall"],
                        "meta": g["label"],
                        "reason": "informative feature at {f_hz:g} Hz, {db:+.1f} dB".format(
                            **g["probes"]["feature"]
                        ),
                        "tone": "yes"
                        if g["overall"] == "reachable"
                        else "no"
                        if g["overall"] == "unreachable"
                        else "none",
                    }
                    for key, g in gates.items()
                ],
            ),
            table(
                "probes",
                ["readout", "probe", "f (Hz)", "gain (dB)", "verdict"],
                [
                    [key, name, p["f_hz"], p["db"], p["verdict"]]
                    for key, g in gates.items()
                    for name, p in g["probes"].items()
                ],
            ),
        ],
        facts=[
            ("readouts", len(gates)),
            ("reachable", sum(g["overall"] == "reachable" for g in gates.values())),
        ],
    )
