"""Instruction-following generators (IFEval-style). Every constraint is a
deterministic predicate over the answer text (line counts, prefixes, forbidden
words, length bounds), graded by the 'constraints' grader — no LLM judge, no keyword
guessing. This fills a gap the audit flagged: the benchmark had no verifiable
instruction-following family, only open-ended 'creativity'.

New family 'instruction_following' (added to families.py)."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "instruction_following."

_TOPICS = ("renewable energy", "coffee brewing", "urban gardening", "tide pools",
           "chess openings", "paper airplanes", "sourdough", "meteor showers",
           "bicycle maintenance", "origami")


def _mk(gid, sub, prompt, grader, example, rng, *, diff, pts=3, neg=1, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "instruction_following", sub,
                    prompt + canary_suffix(c), "rubric",
                    server_grader=grader, expected_answer=example, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c,
                    modality=["text"])


@register(_GID + "numbered_lines", "instruction_following")
def numbered_lines(rng, idx, vis):
    """Produce exactly N lines, each starting with a required prefix."""
    n = rng.randint(3, 6)
    topic = rng.choice(_TOPICS)
    prefix = rng.choice(("- ", "* ", "Fact: ", "Tip: "))
    p = (f"Write exactly {n} short tips about {topic}. Put each tip on its own line. "
         f"Every line must begin with '{prefix}'. Output nothing else.")
    checks = [
        {"kind": "line_count", "n": n},
        {"kind": "line_prefix", "prefix": prefix.strip() if prefix.strip() else prefix},
    ]
    example = "\n".join(f"{prefix}{topic} point number {i + 1}" for i in range(n))
    g = {"type": "constraints", "checks": checks, "example": example}
    return _mk(_GID + "numbered_lines", "format_constraints", p, g, example, rng,
               diff=3.5, vis=vis)


@register(_GID + "forbidden_word", "instruction_following")
def forbidden_word(rng, idx, vis):
    """Answer within a word budget while avoiding a forbidden word and including a
    required keyword."""
    topic = rng.choice(_TOPICS)
    forbidden = rng.choice(("very", "really", "thing", "good", "nice"))
    required = rng.choice(("therefore", "however", "specifically", "notably"))
    max_words = rng.choice((30, 40, 50))
    p = (f"Write a short paragraph about {topic}. Requirements: use at most "
         f"{max_words} words, include the word '{required}' at least once, and never "
         f"use the word '{forbidden}'.")
    checks = [
        {"kind": "max_words", "n": max_words},
        {"kind": "must_contain", "term": required},
        {"kind": "must_not_contain", "term": forbidden},
    ]
    example = (f"{topic.capitalize()} rewards patience; {required}, steady practice "
               "compounds into real skill over time.")
    g = {"type": "constraints", "checks": checks, "example": example}
    return _mk(_GID + "forbidden_word", "lexical_constraints", p, g, example, rng,
               diff=4.0, vis=vis)


@register(_GID + "structured_reply", "instruction_following")
def structured_reply(rng, idx, vis):
    """Every line must contain a required marker and the reply has a length floor."""
    topic = rng.choice(_TOPICS)
    marker = rng.choice(("=>", "::", "—"))
    n = rng.randint(3, 5)
    p = (f"List {n} steps for getting started with {topic}. Put each step on its own "
         f"line, and every line must contain the marker '{marker}' separating a short "
         "title from its description. Output only the lines.")
    checks = [
        {"kind": "line_count", "n": n},
        {"kind": "each_line_contains", "term": marker},
    ]
    example = "\n".join(f"Step {i + 1} {marker} do the {i + 1}th thing about {topic}"
                        for i in range(n))
    g = {"type": "constraints", "checks": checks, "example": example}
    return _mk(_GID + "structured_reply", "format_constraints", p, g, example, rng,
               diff=4.0, vis=vis)
