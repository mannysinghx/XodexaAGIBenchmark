"""Science-family generators: dimensional reasoning, stoichiometry-style numeric,
experiment critique (confounds), causal identification, and statistics interpretation."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "science."


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=2, vis, risk="none"):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "science", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c, risk_domain=risk)


@register(_GID + "kinematics", "science")
def kinematics(rng, idx, vis):
    """Constant-acceleration distance."""
    u = rng.randint(0, 10)
    a = rng.randint(1, 5)
    t = rng.randint(2, 8)
    d = u * t + 0.5 * a * t * t
    p = (f"An object starts at {u} m/s and accelerates uniformly at {a} m/s^2 for {t} s. "
         f"How far does it travel (in metres)? Give only the number.")
    return _mk(_GID + "kinematics", "physics", p, "numeric",
               {"type": "numeric", "target": round(d, 3), "tolerance": 0.05}, round(d, 2),
               rng, diff=4.0, vis=vis)


@register(_GID + "stoichiometry", "science")
def stoichiometry(rng, idx, vis):
    """Mole arithmetic."""
    mass = rng.randint(10, 200)
    molar = rng.choice([18, 44, 28, 32, 16])
    moles = mass / molar
    p = (f"How many moles are in {mass} g of a compound with molar mass {molar} g/mol? "
         f"Give the answer to 2 decimal places.")
    return _mk(_GID + "stoichiometry", "chemistry", p, "numeric",
               {"type": "numeric", "target": round(moles, 4), "tolerance": 0.02},
               round(moles, 2), rng, diff=3.5, vis=vis)


@register(_GID + "confound_critique", "science")
def confound_critique(rng, idx, vis):
    """Identify the confound in a study design."""
    p = ("A study reports that people who drink more coffee live longer. It concludes "
         "coffee extends lifespan. The study did not adjust for smoking, exercise, or "
         "income. Identify the single biggest methodological problem with the causal "
         "conclusion in one sentence.")
    g = {"type": "rubric_keywords",
         "keywords": ["confound", "causation"],
         "pass_fraction": 0.5,
         "penalty_if_contains_any": ["coffee definitely extends", "proves coffee causes"]}
    return _mk(_GID + "confound_critique", "experimental_design", p, "rubric", g,
               "Confounding: correlation is not causation; unadjusted confounders.",
               rng, diff=5.0, pts=4, neg=2, vis=vis, risk="medical_safe")


@register(_GID + "causal_identification", "science")
def causal_identification(rng, idx, vis):
    """MCQ: which variable is the confounder."""
    g = {"type": "mcq", "correct": "C",
         "options": {"A": "ice cream sales", "B": "drowning deaths",
                     "C": "hot weather", "D": "swimsuit prices"}}
    p = ("Ice cream sales and drowning deaths rise together each summer. Which option is "
         "the most likely common cause (confounder) explaining the correlation?\n"
         "A) ice cream sales\nB) drowning deaths\nC) hot weather\nD) swimsuit prices\n"
         "Answer with the letter.")
    return _mk(_GID + "causal_identification", "causal_inference", p, "exact", g, "C",
               rng, diff=3.5, vis=vis)


@register(_GID + "stats_interpretation", "science")
def stats_interpretation(rng, idx, vis):
    """p-value interpretation trap."""
    p = ("A trial reports p = 0.03 for a drug effect. A colleague says this means there "
         "is a 97% probability the drug works. State whether that interpretation is "
         "correct and what p = 0.03 actually means, in one or two sentences.")
    g = {"type": "rubric_keywords",
         "keywords": ["null hypothesis", "if"],
         "pass_fraction": 0.5,
         "penalty_if_contains_any": ["yes that is correct", "97% probability the drug works is correct"]}
    return _mk(_GID + "stats_interpretation", "stats_interpretation", p, "rubric", g,
               "Incorrect: p is P(data this extreme | null true), not P(hypothesis).",
               rng, diff=5.5, pts=4, neg=3, vis=vis)


@register(_GID + "half_life", "science")
def half_life(rng, idx, vis):
    """Exponential decay over integer half-lives."""
    init = rng.choice([80, 100, 160, 200])
    halves = rng.randint(2, 5)
    ans = init / (2 ** halves)
    p = (f"A sample of {init} mg decays with a half-life such that exactly {halves} "
         f"half-lives elapse. How many mg remain? Give only the number.")
    return _mk(_GID + "half_life", "physics", p, "numeric",
               {"type": "numeric", "target": round(ans, 4), "tolerance": 0.01}, round(ans, 3),
               rng, diff=4.0, vis=vis)
