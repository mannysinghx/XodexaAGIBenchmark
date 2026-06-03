"""Mathematics-family generators: modular exponentiation, combinatorics, number
theory, probability, linear systems, and a false-proof trap."""

from __future__ import annotations

from math import comb, gcd

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "math."


def _mk(gid, sub, prompt, grader, ans, rng, *, diff, atype="numeric", pts=3, neg=2, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "math", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c)


@register(_GID + "modular_exponentiation", "math")
def modular_exponentiation(rng, idx, vis):
    """Compute a^b mod m."""
    a, b, m = rng.randint(2, 12), rng.randint(5, 40), rng.choice([7, 11, 13, 97, 1000])
    ans = pow(a, b, m)
    p = f"Compute {a}^{b} mod {m}. Give only the integer result."
    return _mk(_GID + "modular_exponentiation", "number_theory", p,
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=5.0, vis=vis)


@register(_GID + "combinatorics_choose", "math")
def combinatorics_choose(rng, idx, vis):
    """Binomial coefficient."""
    n = rng.randint(8, 18)
    k = rng.randint(2, n - 2)
    ans = comb(n, k)
    p = f"How many ways are there to choose {k} items from {n} distinct items? Give only the number."
    return _mk(_GID + "combinatorics_choose", "combinatorics", p,
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=4.5, vis=vis)


@register(_GID + "divisor_count", "math")
def divisor_count(rng, idx, vis):
    """Count divisors of n."""
    n = rng.randint(40, 400)
    d = sum(1 for i in range(1, n + 1) if n % i == 0)
    p = f"How many positive divisors does {n} have? Give only the number."
    return _mk(_GID + "divisor_count", "number_theory", p,
               {"type": "numeric", "target": float(d), "tolerance": 0.001}, d,
               rng, diff=5.0, vis=vis)


@register(_GID + "gcd_pair", "math")
def gcd_pair(rng, idx, vis):
    """Greatest common divisor."""
    a, b = rng.randint(100, 999), rng.randint(100, 999)
    ans = gcd(a, b)
    p = f"What is the greatest common divisor of {a} and {b}? Give only the number."
    return _mk(_GID + "gcd_pair", "number_theory", p,
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=3.5, vis=vis)


@register(_GID + "probability_fraction", "math")
def probability_fraction(rng, idx, vis):
    """Probability as a reduced value."""
    total = rng.randint(6, 12)
    good = rng.randint(1, total - 1)
    ans = good / total
    p = (f"An urn holds {total} balls, {good} of them red. One ball is drawn at random. "
         f"What is the probability it is red? Give the value as a decimal or fraction.")
    return _mk(_GID + "probability_fraction", "probability", p,
               {"type": "numeric", "target": round(ans, 6), "tolerance": 0.01}, round(ans, 4),
               rng, diff=4.0, vis=vis)


@register(_GID + "linear_system", "math")
def linear_system(rng, idx, vis):
    """Solve a 2x2 linear system for x."""
    x, y = rng.randint(-6, 9), rng.randint(-6, 9)
    a, b, c, d = (rng.randint(1, 5), rng.randint(1, 5), rng.randint(1, 5), rng.randint(1, 5))
    e1, e2 = a * x + b * y, c * x + d * y
    if a * d - b * c == 0:
        d += 1
        e2 = c * x + d * y
    p = (f"Solve the system for x:\n  {a}x + {b}y = {e1}\n  {c}x + {d}y = {e2}\n"
         f"Give only the value of x.")
    return _mk(_GID + "linear_system", "algebra", p,
               {"type": "numeric", "target": float(x), "tolerance": 0.01}, x,
               rng, diff=4.5, vis=vis)


@register(_GID + "false_proof_primes", "math")
def false_proof_primes(rng, idx, vis):
    """A classic false-premise proof that must be rejected."""
    p = ("Given the premise that all prime numbers are odd, prove that the sum of any "
         "two primes is even. Proceed.")
    g = {"type": "flag_false_premise",
         "must_contain_any": ["2 is prime", "2 is even", "two is even", "only even prime",
                              "premise is false", "false premise", "not all primes are odd"],
         "penalty_if_contains_any": ["therefore the sum is always even", "qed", "thus proven"]}
    return _mk(_GID + "false_proof_primes", "proof", p, g,
               "Reject: 2 is an even prime, so the premise is false.", rng,
               diff=5.0, atype="rubric", pts=4, neg=3, vis=vis)


@register(_GID + "summation", "math")
def summation(rng, idx, vis):
    """Closed-form summation."""
    n = rng.randint(10, 60)
    ans = n * (n + 1) // 2
    p = f"What is the sum of all integers from 1 to {n} inclusive? Give only the number."
    return _mk(_GID + "summation", "algebra", p,
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=2.5, vis=vis)
