"""Code-family generators: predict-output, bug identification, complexity, and a
safe vulnerability-class identification task. Graders are deterministic; in a full
deployment these would map onto hidden unit tests in a Docker sandbox."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "code."


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=2, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "code", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c, modality=["text", "code"])


@register(_GID + "predict_output", "code")
def predict_output(rng, idx, vis):
    """Predict the return value of a small pure function."""
    n = rng.randint(3, 9)
    # sum of squares of 0..n-1
    ans = sum(i * i for i in range(n))
    snippet = (f"def f(n):\n    t = 0\n    for i in range(n):\n        t += i * i\n"
               f"    return t\n\nprint(f({n}))")
    p = ("What does this Python program print?\n\n```python\n" + snippet +
         "\n```\nGive only the printed value.")
    return _mk(_GID + "predict_output", "fresh_coding", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=3.5, vis=vis)


@register(_GID + "off_by_one_bug", "code")
def off_by_one_bug(rng, idx, vis):
    """Find the bug class in a buggy snippet."""
    snippet = ("def last_index(xs):\n    i = 0\n    while i <= len(xs):\n"
               "        i += 1\n    return i - 1")
    p = ("This function is supposed to return the last valid index of a non-empty list "
         "but it has a bug.\n\n```python\n" + snippet + "\n```\n"
         "Name the bug class and the fix in one short sentence.")
    g = {"type": "rubric_keywords", "keywords": ["off-by-one", "len"],
         "pass_fraction": 0.5,
         "penalty_if_contains_any": ["no bug", "code is correct", "works correctly"]}
    return _mk(_GID + "off_by_one_bug", "bugfix", p, "rubric", g,
               "Off-by-one: `i <= len(xs)` should be `i < len(xs)`.", rng,
               diff=4.5, pts=4, neg=2, vis=vis)


@register(_GID + "complexity", "code")
def complexity(rng, idx, vis):
    """Identify the time complexity (MCQ)."""
    g = {"type": "mcq", "correct": "C",
         "options": {"A": "O(1)", "B": "O(n)", "C": "O(n^2)", "D": "O(log n)"}}
    snippet = ("def f(a):\n    c = 0\n    for i in a:\n        for j in a:\n"
               "            c += i * j\n    return c")
    p = ("What is the time complexity of this function in terms of len(a) = n?\n\n```python\n"
         + snippet + "\n```\nA) O(1)  B) O(n)  C) O(n^2)  D) O(log n)\nAnswer with the letter.")
    return _mk(_GID + "complexity", "review", p, "exact", g, "C", rng, diff=4.0, vis=vis)


@register(_GID + "vuln_class_id", "code")
def vuln_class_id(rng, idx, vis):
    """Identify an injection vulnerability class in a safe toy snippet (defensive)."""
    snippet = ('def lookup(db, user_input):\n'
               '    q = "SELECT * FROM users WHERE name = \'" + user_input + "\'"\n'
               '    return db.execute(q)')
    p = ("This toy function builds a database query from user input.\n\n```python\n"
         + snippet + "\n```\nName the vulnerability class and the standard defensive fix "
         "(one sentence). Do not write any exploit.")
    g = {"type": "rubric_keywords",
         "keywords": ["sql injection", "parameter"],
         "pass_fraction": 0.5,
         "penalty_if_contains_any": ["no vulnerability", "code is safe"]}
    return _mk(_GID + "vuln_class_id", "security_patch", p, "rubric", g,
               "SQL injection; fix with parameterized queries / prepared statements.",
               rng, diff=5.0, pts=4, neg=2, vis=vis)


@register(_GID + "refactor_equiv", "code")
def refactor_equiv(rng, idx, vis):
    """Predict output of code after a described refactor (semantics preserved)."""
    xs = [rng.randint(1, 9) for _ in range(rng.randint(4, 6))]
    ans = max(xs) - min(xs)
    p = ("A function returns max(xs) - min(xs). For xs = " + str(xs) +
         ", what does it return? Give only the number.")
    return _mk(_GID + "refactor_equiv", "refactor", p, "numeric",
               {"type": "numeric", "target": float(ans), "tolerance": 0.001}, ans,
               rng, diff=2.5, vis=vis)
