"""Creativity & synthesis generators. Creativity is hard to grade deterministically,
so these tasks impose *objective, machine-checkable constraints* (acrostics, length
and lexical constraints, required elements) — measuring constraint-satisfied
originality rather than subjective 'quality'. Graders use regex / keyword rubrics."""

from __future__ import annotations

import string

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "creativity."


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=1, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "creativity", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c)


@register(_GID + "alliteration", "creativity")
def alliteration(rng, idx, vis):
    """Write a sentence where (almost) every word starts with a given letter."""
    letter = rng.choice("bcdfgmprst")
    p = (f"Write a single grammatical sentence of at least 6 words in which every word "
         f"begins with the letter '{letter}'. Output only the sentence.")
    # 6+ words each starting with the letter, ending in a period.
    pat = rf"^(?:\W*{letter}\w*\W+){{5,}}{letter}\w*\W*$"
    g = {"type": "regex", "pattern": pat, "ignorecase": True,
         "example": " ".join([letter + "ad"] * 6) + "."}
    return _mk(_GID + "alliteration", "constraint_satisfaction", p, "rubric", g,
               f"A 6+ word sentence alliterating on '{letter}'.", rng, diff=4.0, vis=vis)


@register(_GID + "acrostic", "creativity")
def acrostic(rng, idx, vis):
    """Produce N lines whose first letters spell a given word."""
    word = "".join(rng.choice(string.ascii_uppercase) for _ in range(rng.randint(3, 4)))
    lines = r"\s*".join(rf"{ch}\w*.*" for ch in word)
    p = (f"Write a short {len(word)}-line poem that is an acrostic of the word '{word}': "
         f"the first letter of each line, read top to bottom, spells '{word}'. One line "
         f"per row.")
    g = {"type": "regex", "pattern": r"(?m)^\s*" + lines, "ignorecase": True,
         "example": "\n".join(ch + "verse here" for ch in word)}
    return _mk(_GID + "acrostic", "design", p, "rubric", g,
               f"Acrostic spelling {word}.", rng, diff=4.5, vis=vis)


@register(_GID + "constrained_design", "creativity")
def constrained_design(rng, idx, vis):
    """Propose a design that mentions all required elements."""
    reqs = rng.sample(["solar", "modular", "waterproof", "recyclable", "lightweight",
                       "low-cost"], 3)
    p = ("Propose a one-paragraph product concept for a backpack that is explicitly "
         f"ALL of the following: {', '.join(reqs)}. Mention each property by name.")
    g = {"type": "rubric_keywords", "keywords": reqs, "pass_fraction": 1.0}
    return _mk(_GID + "constrained_design", "synthesis", p, "rubric", g,
               "Concept covering all required properties.", rng, diff=3.5, pts=3, neg=0, vis=vis)
