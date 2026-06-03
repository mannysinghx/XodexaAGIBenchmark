"""Strategy & decision-making generators: expected-value choice, resource allocation,
trend forecasting, and tradeoff reasoning. Quantitative items are graded numerically;
qualitative items use a keyword rubric with penalties for unsupported certainty."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "strategy."


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=2, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "strategy", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c)


@register(_GID + "expected_value", "strategy")
def expected_value(rng, idx, vis):
    """Compute the expected value of a bet."""
    p_win = rng.choice([0.2, 0.25, 0.3, 0.4, 0.5])
    win = rng.randint(50, 200)
    loss = rng.randint(10, 80)
    ev = p_win * win - (1 - p_win) * loss
    p = (f"A bet wins ${win} with probability {p_win} and otherwise loses ${loss}. "
         f"What is the expected value in dollars? Give the number (negative if a loss).")
    return _mk(_GID + "expected_value", "risk_assessment", p, "numeric",
               {"type": "numeric", "target": round(ev, 4), "tolerance": 0.05}, round(ev, 2),
               rng, diff=4.0, vis=vis)


@register(_GID + "resource_allocation", "strategy")
def resource_allocation(rng, idx, vis):
    """Pick the project with the highest ROI (return per dollar)."""
    projs = {}
    for nm in ["Atlas", "Beacon", "Cedar"]:
        cost = rng.randint(10, 50)
        ret = rng.randint(15, 120)
        projs[nm] = (cost, ret, ret / cost)
    best = max(projs, key=lambda k: projs[k][2])
    lines = "\n".join(f"  {k}: cost ${v[0]}k, return ${v[1]}k" for k, v in projs.items())
    p = ("With a fixed budget, which single project gives the highest return per dollar?\n"
         + lines + f"\nAnswer with the project name ({'/'.join(projs)}).")
    return _mk(_GID + "resource_allocation", "resource_allocation", p, "exact",
               {"type": "exact", "accept": [best]}, best, rng, diff=4.5, vis=vis)


@register(_GID + "forecast_trend", "strategy")
def forecast_trend(rng, idx, vis):
    """Linear trend extrapolation."""
    start = rng.randint(100, 300)
    step = rng.randint(5, 40)
    series = [start + step * i for i in range(5)]
    nxt = start + step * 5
    p = ("Monthly revenue followed this linear trend ($k): " + ", ".join(map(str, series)) +
         ". Assuming the trend continues, forecast next month. Give only the number.")
    return _mk(_GID + "forecast_trend", "forecasting", p, "numeric",
               {"type": "numeric", "target": float(nxt), "tolerance": 0.001}, nxt,
               rng, diff=3.5, vis=vis)


@register(_GID + "tradeoff_reasoning", "strategy")
def tradeoff_reasoning(rng, idx, vis):
    """Qualitative tradeoff: must name both sides + a recommendation."""
    p = ("A startup can either ship a feature fast with technical debt, or delay two "
         "months to build it cleanly. In 1-2 sentences, name the key tradeoff on BOTH "
         "sides and give a clear recommendation with its main risk.")
    g = {"type": "rubric_keywords",
         "keywords": ["debt", "risk", "recommend"],
         "pass_fraction": 0.66,
         "penalty_if_contains_any": ["there is no tradeoff", "no downside"]}
    return _mk(_GID + "tradeoff_reasoning", "tradeoff", p, "rubric", g,
               "Name speed-vs-quality tradeoff, recommend with stated risk.", rng,
               diff=5.0, pts=4, neg=1, vis=vis)
