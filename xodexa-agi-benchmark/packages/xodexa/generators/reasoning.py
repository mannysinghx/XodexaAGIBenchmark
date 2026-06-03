"""Reasoning-family generators: symbolic transforms, hidden-rule induction, sequence
extrapolation, compositional arithmetic, analogy transfer, adversarial logic."""

from __future__ import annotations

import string

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "reasoning."


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=2, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "reasoning", sub, prompt + canary_suffix(c),
                    atype, server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c)


@register(_GID + "symbolic_strings", "reasoning")
def symbolic_strings(rng, idx, vis):
    """Apply a described string transformation."""
    word = "".join(rng.choice(string.ascii_lowercase) for _ in range(rng.randint(5, 8)))
    k = rng.randint(1, 4)
    out = "".join(chr((ord(ch) - 97 + k) % 26 + 97) for ch in word)[::-1]
    p = (f"Apply this transformation to the input string: (1) shift every letter "
         f"forward by {k} in the alphabet (wrapping z->a), then (2) reverse the result.\n"
         f"INPUT: {word}\nGive only the transformed string.")
    return _mk(_GID + "symbolic_strings", "symbolic_strings", p, "exact",
               {"type": "exact", "accept": [out]}, out, rng, diff=3.5, vis=vis)


@register(_GID + "hidden_rule_induction", "reasoning")
def hidden_rule_induction(rng, idx, vis):
    """Induce a hidden numeric mapping from examples, then apply it."""
    a, b = rng.randint(2, 5), rng.randint(1, 9)
    xs = rng.sample(range(2, 20), 4)
    ex = "\n".join(f"  f({x}) = {a*x + b}" for x in xs)
    q = rng.randint(20, 40)
    ans = a * q + b
    p = (f"A function f follows a single hidden rule. Examples:\n{ex}\n"
         f"What is f({q})? Give only the number.")
    return _mk(_GID + "hidden_rule_induction", "hidden_rule_induction", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=4.0, vis=vis)


@register(_GID + "sequence_extrapolation", "reasoning")
def sequence_extrapolation(rng, idx, vis):
    """Extrapolate a quadratic/arithmetic sequence."""
    a, b, c = rng.randint(1, 3), rng.randint(-3, 4), rng.randint(0, 5)
    seq = [a * n * n + b * n + c for n in range(1, 6)]
    nxt = a * 36 + b * 6 + c
    p = ("Find the next term of this sequence:\n  " + ", ".join(map(str, seq)) +
         ", ?\nGive only the next integer.")
    return _mk(_GID + "sequence_extrapolation", "sequence_extrapolation", p, "numeric",
               {"type": "numeric", "target": float(nxt), "tolerance": 0.001}, nxt,
               rng, diff=4.5, vis=vis)


@register(_GID + "compositional_arithmetic", "reasoning")
def compositional_arithmetic(rng, idx, vis):
    """Compose two defined functions and evaluate."""
    a, b, cst = rng.randint(2, 6), rng.randint(1, 9), rng.randint(1, 9)
    n = rng.randint(2, 7)
    g = n * n - cst
    ans = a * g + b
    p = (f"Let f(x) = {a}x + {b} and g(x) = x^2 - {cst}. Compute f(g({n})). "
         f"Give only the number.")
    return _mk(_GID + "compositional_arithmetic", "compositional", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=5.0, vis=vis)


@register(_GID + "analogy_transfer", "reasoning")
def analogy_transfer(rng, idx, vis):
    """Letter-position analogy."""
    base = rng.randint(1, 20)
    step = rng.randint(2, 5)
    A = string.ascii_uppercase[base - 1]
    B = string.ascii_uppercase[(base - 1 + step) % 26]
    C = string.ascii_uppercase[(base - 1 + 7) % 26]
    D = string.ascii_uppercase[(base - 1 + 7 + step) % 26]
    p = (f"{A} is to {B} as {C} is to ?  (Apply the same alphabetical shift.) "
         f"Give only the single letter.")
    return _mk(_GID + "analogy_transfer", "analogy_transfer", p, "exact",
               {"type": "exact", "accept": [D]}, D, rng, diff=3.0, vis=vis)


@register(_GID + "adversarial_logic", "reasoning")
def adversarial_logic(rng, idx, vis):
    """A false-premise logic trap that must be rejected."""
    p = ("Given the premise that every multiple of 4 is also a multiple of 8, prove "
         "that 12 is a multiple of 8. Proceed with the proof.")
    g = {"type": "flag_false_premise",
         "must_contain_any": ["premise is false", "false premise", "not every multiple",
                              "12 is not", "4 is a multiple of 4", "premise is wrong",
                              "incorrect premise", "counterexample"],
         "penalty_if_contains_any": ["therefore 12 is a multiple of 8", "qed",
                                     "thus proven", "hence 12 is a multiple of 8"]}
    return _mk(_GID + "adversarial_logic", "adversarial_logic", p, "rubric",
               g, "Reject the premise: 12 = 4×3 is a multiple of 4 but not of 8.",
               rng, diff=5.5, pts=4, neg=3, vis=vis)


@register(_GID + "counterfactual", "reasoning")
def counterfactual(rng, idx, vis):
    """Counterfactual arithmetic under a redefined operator."""
    base = rng.randint(3, 9)
    n = rng.randint(2, 6)
    # In this world, "+" means "multiply then add 1".
    ans = base * n + 1
    p = (f"In a hypothetical arithmetic, the symbol '+' is redefined so that a + b "
         f"means (a × b) + 1. Under this rule, what is {base} + {n}? Give only the number.")
    return _mk(_GID + "counterfactual", "counterfactual", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001,
                "penalty_if_numeric_near": [base + n]}, ans, rng, diff=4.5, vis=vis)
