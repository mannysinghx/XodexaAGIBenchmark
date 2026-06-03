"""Memory & long-context generators: needle-in-haystack, multi-needle summation,
in-order state tracking through distractors, and contradiction tracking — all built
from procedurally generated filler so the haystack is unique per seed (anti-memorization)."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "memory."

_SUBJ = ["The logistics committee", "A visiting auditor", "The night supervisor",
         "The archivist", "A junior analyst", "The maintenance crew",
         "The procurement office", "An external consultant", "The records desk"]
_VERB = ["reviewed", "catalogued", "reorganized", "annotated", "inspected",
         "summarized", "filed", "double-checked", "cross-referenced"]
_OBJ = ["the corridor lighting schedule", "old delivery manifests", "the cafeteria rota",
        "outdated floor plans", "the visitor sign-in log", "spare office chairs",
        "the recycling pickup times", "a memo about parking permits",
        "the fire-drill attendance sheet"]


def _filler(rng, n):
    return [f"{rng.choice(_SUBJ)} {rng.choice(_VERB)} {rng.choice(_OBJ)}." for _ in range(n)]


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=1, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "memory", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c)


@register(_GID + "needle_code", "memory")
def needle_code(rng, idx, vis):
    """Recall a single authorization code buried in filler."""
    code = "%c%c-%04d" % (rng.randint(65, 90), rng.randint(65, 90), rng.randint(1000, 9999))
    f = _filler(rng, rng.randint(120, 220))
    f.insert(int(len(f) * rng.uniform(0.3, 0.8)),
             f"Important operational note: the authorization code for the east archive is {code}.")
    p = ("Read the operations log, then answer.\n\n=== BEGIN LOG ===\n" + " ".join(f)
         + "\n=== END LOG ===\n\nQUESTION: What is the authorization code for the east "
           "archive? Reply with the code exactly.")
    return _mk(_GID + "needle_code", "needle", p, "exact",
               {"type": "exact", "accept": [code]}, code, rng, diff=4.0, vis=vis)


@register(_GID + "multi_needle_sum", "memory")
def multi_needle_sum(rng, idx, vis):
    """Sum K sensor readings scattered through distractor numbers."""
    k = rng.randint(4, 6)
    nums = [rng.randint(10, 99) for _ in range(k)]
    names = rng.sample(["Alpha", "Bravo", "Cobalt", "Delta", "Echo", "Foxtrot", "Gamma"], k)
    f = _filler(rng, rng.randint(160, 240))
    for nm, v in zip(names, nums):
        f.insert(rng.randint(0, len(f)), f"Sensor {nm} reported a reading of {v} units.")
    p = (f"Exactly {k} sentences below report a numeric 'sensor reading'. Ignore every "
         f"other number.\n\n=== BEGIN REPORT ===\n" + " ".join(f) + "\n=== END REPORT ===\n\n"
         "QUESTION: Add ONLY the sensor readings. Give only the total.")
    return _mk(_GID + "multi_needle_sum", "multi_needle", p, "numeric",
               {"type": "numeric", "target": float(sum(nums)), "tolerance": 0.001},
               sum(nums), rng, diff=5.0, vis=vis)


@register(_GID + "state_track", "memory")
def state_track(rng, idx, vis):
    """Apply ordered counter operations interleaved with filler."""
    val = rng.randint(20, 60)
    start = val
    steps = []
    for i in range(1, rng.randint(9, 14)):
        kind = rng.choice(["add", "sub", "double", "add", "sub"])
        if kind == "add":
            k = rng.randint(2, 12); val += k; steps.append(f"Step {i}: increase the counter by {k}.")
        elif kind == "sub":
            k = rng.randint(2, 9); val -= k; steps.append(f"Step {i}: decrease the counter by {k}.")
        else:
            val *= 2; steps.append(f"Step {i}: double the counter.")
    f = _filler(rng, rng.randint(120, 180))
    merged, fi = [], 0
    per = max(1, len(f) // (len(steps) + 1))
    for s in steps:
        merged += f[fi:fi + per]; fi += per; merged.append(s)
    merged += f[fi:]
    p = (f"A counter starts at {start}. Apply every numbered Step in order; ignore other "
         f"notes.\n\n=== BEGIN DOCUMENT ===\n" + " ".join(merged) + "\n=== END DOCUMENT ===\n\n"
         "QUESTION: What is the final counter value? Give only the number.")
    return _mk(_GID + "state_track", "delayed_instruction", p, "numeric",
               {"type": "numeric", "target": float(val), "tolerance": 0.001}, val,
               rng, diff=5.5, vis=vis)


@register(_GID + "contradiction_tracking", "memory")
def contradiction_tracking(rng, idx, vis):
    """Detect a single internal contradiction across a long document."""
    y1 = rng.randint(1850, 1920)
    y2 = y1 + rng.randint(20, 60)
    f = _filler(rng, rng.randint(150, 220))
    f.insert(int(len(f) * 0.25), f"Historical note: the old vault was sealed in {y1}.")
    f.insert(int(len(f) * 0.75), f"Per the building registry, the old vault was sealed in {y2}.")
    p = ("Read the document.\n\n=== BEGIN DOCUMENT ===\n" + " ".join(f) +
         "\n=== END DOCUMENT ===\n\nQUESTION: The document gives conflicting information "
         "about ONE fact (the year the vault was sealed). State that it is contradictory "
         "and give BOTH years.")
    return _mk(_GID + "contradiction_tracking", "contradiction_tracking", p, "rubric",
               {"type": "contains_all", "terms": [str(y1), str(y2)], "allow_partial": True},
               f"Contradiction: {y1} vs {y2}.", rng, diff=5.0, pts=4, neg=2, vis=vis)
