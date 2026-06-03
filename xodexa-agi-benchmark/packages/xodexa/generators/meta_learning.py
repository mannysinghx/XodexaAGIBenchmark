"""Meta-learning & adaptation generators: learn a novel operator defined inside the
task, transfer a pattern from few examples, adapt after a corrected wrong assumption,
and self-correct. All graders are numeric/exact so 'did it actually learn the rule'
is unambiguous."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "meta_learning."


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=2, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "meta_learning", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c)


@register(_GID + "novel_operator", "meta_learning")
def novel_operator(rng, idx, vis):
    """Define a brand-new operator and require its application."""
    a, b = rng.randint(2, 9), rng.randint(2, 9)
    # a ⊕ b = a*a + b
    ans = a * a + b
    p = (f"Define a new operator ⊕ such that x ⊕ y = (x squared) + y. "
         f"Examples: 3 ⊕ 4 = 13, 5 ⊕ 1 = 26. Compute {a} ⊕ {b}. Give only the number.")
    return _mk(_GID + "novel_operator", "in_context_rule", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=4.0, vis=vis)


@register(_GID + "few_shot_transfer", "meta_learning")
def few_shot_transfer(rng, idx, vis):
    """Infer a 2-feature rule from examples and apply to a new case."""
    # rule: output = 1 if (x even and y > 5) else 0
    def rule(x, y):
        return 1 if (x % 2 == 0 and y > 5) else 0
    ex = [(rng.randint(1, 10), rng.randint(1, 10)) for _ in range(5)]
    lines = "\n".join(f"  x={x}, y={y} -> {rule(x, y)}" for x, y in ex)
    qx, qy = rng.randint(1, 10), rng.randint(1, 10)
    p = (f"Each row maps (x, y) to 0 or 1 by a hidden rule:\n{lines}\n"
         f"What does x={qx}, y={qy} map to? Give only 0 or 1.")
    return _mk(_GID + "few_shot_transfer", "few_shot_transfer", p, "numeric",
               {"type": "numeric", "target": float(rule(qx, qy)), "tolerance": 0.001},
               rule(qx, qy), rng, diff=5.0, vis=vis)


@register(_GID + "feedback_adaptation", "meta_learning")
def feedback_adaptation(rng, idx, vis):
    """A wrong assumption is corrected mid-task; recompute under the correction."""
    base = rng.randint(10, 40)
    # First told to add 10, then corrected: actually multiply by 3.
    ans = base * 3
    p = (f"Task: transform {base}. You were initially told the rule is 'add 10'. "
         f"CORRECTION: the rule is actually 'multiply by 3', not 'add 10'. "
         f"Apply the corrected rule. Give only the number.")
    return _mk(_GID + "feedback_adaptation", "feedback_adaptation", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001,
                "penalty_if_numeric_near": [base + 10]}, ans, rng, diff=4.5, vis=vis)


@register(_GID + "self_correction", "meta_learning")
def self_correction(rng, idx, vis):
    """Spot and fix an embedded arithmetic slip, then give the right total."""
    a, b, c = rng.randint(10, 50), rng.randint(10, 50), rng.randint(10, 50)
    wrong = a + b + c + rng.randint(1, 5)  # deliberately off
    ans = a + b + c
    p = (f"A draft solution claims {a} + {b} + {c} = {wrong}. Check it. If it is wrong, "
         f"give the correct sum. Give only the number.")
    return _mk(_GID + "self_correction", "self_correction", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001,
                "penalty_if_numeric_near": [wrong]}, ans, rng, diff=4.0, vis=vis)
