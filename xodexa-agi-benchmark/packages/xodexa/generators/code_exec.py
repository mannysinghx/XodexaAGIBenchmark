"""Code-family generators graded by REAL EXECUTION against hidden unit tests
(xodexa.sandbox), replacing keyword-matching for write-me-code tasks. The generator
computes every expected output itself (pure Python, same seed), so the hidden tests
and the reference solution can never disagree. The model sees only the spec and the
public examples — the hidden test inputs stay server-side with the grader."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "code."


def _mk(gid, sub, prompt, grader, ans, rng, *, diff, pts=5, neg=1, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "code", sub, prompt + canary_suffix(c), "code_patch",
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c,
                    modality=["text", "code"])


def _spec_prompt(spec: str, sig: str, examples: list[tuple], func="f") -> str:
    ex = "\n".join(f"  {func}({', '.join(map(repr, a))}) -> {r!r}" for a, r in examples)
    return (f"Write a Python function `{sig}` that {spec}\n\nExamples:\n{ex}\n\n"
            "Reply with ONLY the function definition in a ```python code block. "
            "It will be executed against hidden tests.")


@register(_GID + "exec_filter_fold", "code")
def exec_filter_fold(rng, idx, vis):
    """Write a filter+fold function; graded by executing hidden unit tests."""
    k = rng.randint(2, 5)
    op_name, op = rng.choice([("sum", sum), ("product", None)])

    def ref_fn(xs):
        sel = [x for x in xs if x % k == 0]
        if op_name == "sum":
            return sum(sel)
        out = 1
        for x in sel:
            out *= x
        return out

    reference = (f"def f(xs):\n    sel = [x for x in xs if x % {k} == 0]\n"
                 + ("    return sum(sel)" if op_name == "sum" else
                    "    out = 1\n    for x in sel:\n        out *= x\n    return out"))
    cases = [[rng.randint(-9, 20) for _ in range(rng.randint(4, 9))] for _ in range(6)]
    tests = [{"args": [xs], "expect": ref_fn(xs)} for xs in cases]
    examples = [((cases[0],), ref_fn(cases[0]))]
    spec = (f"returns the {op_name} of the elements of the integer list xs that are "
            f"divisible by {k}" + (" (the product of an empty selection is 1)"
                                   if op_name == "product" else ""))
    g = {"type": "code_exec", "func_name": "f", "tests": tests, "reference": reference}
    return _mk(_GID + "exec_filter_fold", "fresh_coding",
               _spec_prompt(spec, "f(xs)", examples), g, reference, rng,
               diff=4.5, vis=vis)


@register(_GID + "exec_fix_bug", "code")
def exec_fix_bug(rng, idx, vis):
    """Fix a buggy function; the FIX is verified by executing hidden tests."""
    lo, hi = sorted(rng.sample(range(-10, 30), 2))
    # Bug: `range(lo, hi)` drops the inclusive upper bound the spec demands.
    buggy = (f"def count_multiples(lo, hi, k):\n"
             f"    return sum(1 for x in range(lo, hi) if x % k == 0)")
    reference = ("def count_multiples(lo, hi, k):\n"
                 "    return sum(1 for x in range(lo, hi + 1) if x % k == 0)")

    def ref_fn(a, b, k):
        return sum(1 for x in range(a, b + 1) if x % k == 0)

    tests = []
    for _ in range(6):
        a, b = sorted(rng.sample(range(-10, 40), 2))
        k = rng.randint(2, 6)
        tests.append({"args": [a, b, k], "expect": ref_fn(a, b, k)})
    # Guarantee at least one case where the off-by-one actually changes the output,
    # so returning the buggy code cannot pass.
    k = rng.randint(2, 6)
    b = k * rng.randint(2, 6)
    tests.append({"args": [b - k, b, k], "expect": ref_fn(b - k, b, k)})
    p = ("This function must count the multiples of k in the INCLUSIVE range "
         "[lo, hi], but it has a bug:\n\n```python\n" + buggy + "\n```\n"
         "Reply with ONLY the corrected function in a ```python code block. "
         "It will be executed against hidden tests.")
    g = {"type": "code_exec", "func_name": "count_multiples", "tests": tests,
         "reference": reference}
    return _mk(_GID + "exec_fix_bug", "bugfix", p, g, reference, rng, diff=4.0, vis=vis)


@register(_GID + "exec_algorithm", "code")
def exec_algorithm(rng, idx, vis):
    """Implement a small seeded algorithm; graded by executing hidden tests."""
    variant = rng.choice(["kth_largest", "rle", "digit_sum_until"])
    if variant == "kth_largest":
        k = rng.randint(1, 3)

        def ref_fn(xs):
            return sorted(xs, reverse=True)[k - 1]

        reference = f"def f(xs):\n    return sorted(xs, reverse=True)[{k - 1}]"
        spec = (f"returns the {k}{'st' if k == 1 else 'nd' if k == 2 else 'rd'}-largest "
                "value in the non-empty integer list xs (duplicates count separately)")
        cases = [[rng.randint(-20, 99) for _ in range(rng.randint(max(3, k), 9))]
                 for _ in range(6)]
    elif variant == "rle":
        def ref_fn(s):
            out, i = [], 0
            while i < len(s):
                j = i
                while j < len(s) and s[j] == s[i]:
                    j += 1
                out.append(s[i] + str(j - i))
                i = j
            return "".join(out)

        reference = ("def f(s):\n    out, i = [], 0\n    while i < len(s):\n"
                     "        j = i\n        while j < len(s) and s[j] == s[i]:\n"
                     "            j += 1\n        out.append(s[i] + str(j - i))\n"
                     "        i = j\n    return ''.join(out)")
        spec = ("run-length encodes the string s: each maximal run of a repeated "
                "character becomes the character followed by the run length "
                "(e.g. 'aaab' -> 'a3b1')")
        cases = ["".join(rng.choice("abc") for _ in range(rng.randint(3, 12)))
                 for _ in range(6)]
    else:
        def ref_fn(n):
            while n >= 10:
                n = sum(int(d) for d in str(n))
            return n

        reference = ("def f(n):\n    while n >= 10:\n"
                     "        n = sum(int(d) for d in str(n))\n    return n")
        spec = ("repeatedly replaces the non-negative integer n with the sum of its "
                "decimal digits until a single digit remains, and returns it")
        cases = [rng.randint(0, 10 ** 6) for _ in range(6)]

    tests = [{"args": [c], "expect": ref_fn(c)} for c in cases]
    examples = [((cases[0],), ref_fn(cases[0]))]
    g = {"type": "code_exec", "func_name": "f", "tests": tests, "reference": reference}
    return _mk(_GID + "exec_algorithm", "fresh_coding",
               _spec_prompt(spec, "f(x)", examples), g, reference, rng,
               diff=5.0, vis=vis)
