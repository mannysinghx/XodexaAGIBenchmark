"""
xodexa.stability
==================
Re-run stability — the reliability signal an AGI-candidate claim actually needs.

Every Xodexa run draws a FRESH seeded pack, so the right question is not "do two runs
agree item-by-item" (the items differ) but "does the model earn a *consistent* score
across independent runs?". A model that swings 200 points between identical-config runs
is not a dependable AGI candidate no matter how high its best run scored.

Given the scores (and optionally per-family scores) of N repeated runs of the SAME model
under the SAME configuration, this module reports the dispersion and a 0..1 stability
index, plus which families are the least reproducible. Pure + dependency-free.
"""

from __future__ import annotations

import statistics

# Score std (on the 0-1000 scale) at which the stability index reaches 0. A std of 100
# points (~a full grade band) is treated as maximally unstable; 0 std -> perfectly stable.
_STABILITY_SCALE = 100.0


def _dispersion(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None,
                "range": None, "cv": None}
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if n > 1 else 0.0
    return {
        "n": n,
        "mean": round(mean, 2),
        "std": round(std, 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "range": round(max(values) - min(values), 2),
        "cv": round(std / mean, 4) if mean else None,  # coefficient of variation
    }


def stability_index(std: float, scale: float = _STABILITY_SCALE) -> float:
    """Map a score standard deviation (0-1000 scale) to a 0..1 reproducibility index:
    1.0 = identical every run, 0.0 = swings by a full grade band or more."""
    return round(max(0.0, 1.0 - (std / scale)), 3)


def rerun_stability(scores: list[float],
                    family_scores: list[dict] | None = None) -> dict:
    """
    scores:        the headline Xodexa Score (0-1000) of each repeated run.
    family_scores: optional per-run {family: 0..1} dicts (e.g. report["family_scores"]),
                   used to flag the least-reproducible families.

    Returns dispersion stats, the stability index, and (if family data is given) the
    families sorted by score volatility. Needs >= 2 runs to be meaningful.
    """
    scores = [float(s) for s in scores if s is not None]
    disp = _dispersion(scores)
    out = {
        "runs": disp["n"],
        "score": disp,
        "stability_index": stability_index(disp["std"]) if disp["std"] is not None else None,
        "sufficient": disp["n"] >= 2,
        "note": ("at least 2 runs of the same model+config are needed to measure stability"
                 if disp["n"] < 2 else
                 "score reproducibility across independent seeded runs of the same model"),
    }
    if family_scores and disp["n"] >= 2:
        fams: dict[str, list[float]] = {}
        for fs in family_scores:
            for fam, val in (fs or {}).items():
                if val is not None:
                    fams.setdefault(fam, []).append(float(val) * 1000.0)  # to 0-1000 scale
        volatility = []
        for fam, vals in fams.items():
            if len(vals) >= 2:
                volatility.append({"family": fam, **_dispersion(vals),
                                   "stability_index": stability_index(statistics.pstdev(vals))})
        volatility.sort(key=lambda f: f["std"], reverse=True)
        out["family_volatility"] = volatility
        out["least_stable_family"] = volatility[0]["family"] if volatility else None
    return out
