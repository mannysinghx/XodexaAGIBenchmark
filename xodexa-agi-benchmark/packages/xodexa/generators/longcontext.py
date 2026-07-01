"""Long-context generators for the memory family — contexts an order of magnitude
beyond the existing memory tasks (tens of thousands of characters, seeded and
deterministic), so retrieval and state-tracking are tested at lengths where models
actually degrade instead of the ~2k-char proxies. The 'xl' variant approaches the
100k-token regime and is intended for dedicated long-context runs (cost note in the
generator blurb)."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "memory."

_SUBJECTS = ("logistics team", "survey drone", "archive daemon", "field station",
             "relay node", "supply convoy", "research pod", "harbor office")
_VERBS = ("reported", "logged", "confirmed", "recorded", "flagged", "archived")
_OBJECTS = ("a routine telemetry sweep", "an inventory reconciliation",
            "a calibration pass", "a maintenance window", "a shift handover",
            "a perimeter check", "a data sync", "a weather reading")


def _filler(rng, n_sentences: int) -> list[str]:
    return [f"The {rng.choice(_SUBJECTS)} {rng.choice(_VERBS)} {rng.choice(_OBJECTS)} "
            f"at {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}."
            for _ in range(n_sentences)]


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts, neg, vis):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "memory", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c,
                    modality=["text"])


def _needle_task(rng, vis, gid, n_sentences: int, diff: float):
    code = "%s-%04d" % ("".join(rng.choice("ABCDEFGHJKMNPQRSTUVWXYZ") for _ in range(2)),
                        rng.randint(1000, 9999))
    sector = rng.choice(("north", "south", "east", "west"))
    needle = (f"For the record, the authorization code for the {sector} archive "
              f"is {code}.")
    sents = _filler(rng, n_sentences)
    sents.insert(rng.randint(n_sentences // 10, n_sentences - 1), needle)
    p = ("Read the following operations log carefully.\n\n" + " ".join(sents) +
         f"\n\nWhat is the authorization code for the {sector} archive? "
         "Reply with the code exactly, nothing else.")
    g = {"type": "exact", "accept": [code]}
    return _mk(gid, "needle_in_haystack", p, "exact", g, code, rng,
               diff=diff, pts=4, neg=2, vis=vis)


@register(_GID + "long_needle", "memory")
def long_needle(rng, idx, vis):
    """Single-needle retrieval from a ~40-60k character log (~10-15k tokens)."""
    return _needle_task(rng, vis, _GID + "long_needle", rng.randint(450, 650), 5.0)


@register(_GID + "long_needle_xl", "memory")
def long_needle_xl(rng, idx, vis):
    """Single-needle retrieval from a ~300k character log (~75k+ tokens).
    COST NOTE: intended for dedicated long-context runs, not default packs."""
    return _needle_task(rng, vis, _GID + "long_needle_xl", rng.randint(3200, 3800), 6.5)


@register(_GID + "long_multi_needle", "memory")
def long_multi_needle(rng, idx, vis):
    """Aggregate 4 scattered numeric facts across ~40k chars into one sum."""
    n = rng.randint(420, 560)
    sents = _filler(rng, n)
    depots = rng.sample(["Kestrel", "Osprey", "Heron", "Petrel", "Avocet", "Curlew"], 4)
    parts = []
    for d in depots:
        v = rng.randint(11, 97)
        parts.append(v)
        sents.insert(rng.randint(0, len(sents)),
                     f"Depot {d} counted exactly {v} sealed crates this cycle.")
    total = sum(parts)
    p = ("Read the following operations log carefully.\n\n" + " ".join(sents) +
         "\n\nAcross the depots " + ", ".join(depots) +
         ", how many sealed crates were counted in total this cycle? "
         "Give only the number.")
    g = {"type": "numeric", "target": float(total), "tolerance": 0.001}
    return _mk(_GID + "long_multi_needle", "multi_needle_aggregation", p, "numeric",
               g, total, rng, diff=5.5, pts=5, neg=2, vis=vis)


@register(_GID + "long_state_tracking", "memory")
def long_state_tracking(rng, idx, vis):
    """Track one register through ~30 interleaved updates buried in ~35k chars."""
    n = rng.randint(380, 520)
    sents = _filler(rng, n)
    target = rng.choice(("R7", "K2", "V9", "M4"))
    decoys = [r for r in ("R7", "K2", "V9", "M4") if r != target]
    value = rng.randint(10, 60)
    updates = [f"Register {target} was initialized to {value}."]
    for _ in range(rng.randint(22, 32)):
        reg = rng.choice([target] * 2 + decoys)  # decoy updates must be ignored
        delta = rng.randint(1, 15)
        op = rng.choice(("increased", "decreased"))
        if reg == target:
            value = value + delta if op == "increased" else value - delta
        updates.append(f"Register {reg} was {op} by {delta}.")
    # Interleave updates into the filler IN ORDER (state tracking demands sequence).
    positions = sorted(rng.sample(range(len(sents)), len(updates)))
    for pos, upd in zip(reversed(positions), reversed(updates)):
        sents.insert(pos, upd)
    p = ("Read the following system log carefully. Register updates appear in "
         "chronological order.\n\n" + " ".join(sents) +
         f"\n\nWhat is the final value of register {target}? Give only the number.")
    g = {"type": "numeric", "target": float(value), "tolerance": 0.001}
    return _mk(_GID + "long_state_tracking", "state_tracking", p, "numeric", g,
               value, rng, diff=6.0, pts=5, neg=2, vis=vis)
