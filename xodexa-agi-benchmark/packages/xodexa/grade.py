"""
xodexa.grade
==============
Self-contained, deterministic graders for Xodexa-generated packs. This is a superset
of the Xodexa-Ω harness grader (same negative-marking philosophy: confident-wrong is
penalized, honest abstention beats fabrication) plus a few types the procedural
generators need (mcq, regex, numeric_set, structured_json, rubric_keywords).

Deterministic + auditable: no LLM judge. Every grader returns
``(awarded, max_points, verdict)``. Negative marking can drive ``awarded`` below 0.

This module is intentionally dependency-free so it runs inside the air-gapped runner
(for comparison-mode local scoring) and inside the central authority alike.
"""

from __future__ import annotations

import json
import re

ABSTAIN_MARKERS = [
    "i don't", "i do not", "i cannot find", "cannot find", "could not find",
    "couldn't find", "no such", "not aware of", "does not exist", "doesn't exist",
    "no record", "no evidence", "unable to", "i'm not able", "i am not able",
    "not a real", "fictional", "made up", "fabricat", "does not appear",
    "no reliable", "not exist", "unverified", "no widely", "i can't find",
    "no information", "appears to be fictional", "i'm not familiar",
    "not familiar with", "no credible", "there is no", "no published",
    "not something i can verify", "be cautious", "likely does not", "no documented",
    "insufficient information", "cannot be determined", "not enough information",
]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def extract_numbers(text: str) -> list[float]:
    vals: list[float] = []
    text = text or ""
    for m in re.finditer(r"(?<![\d.])(\d+)\s*/\s*(\d+)", text):
        a, b = int(m.group(1)), int(m.group(2))
        if b:
            vals.append(a / b)
    for m in re.finditer(r"-?\$?\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?%?|-?\$?\d+(?:\.\d+)?%?", text):
        tok = m.group(0).replace("$", "").replace(",", "").strip()
        pct = tok.endswith("%")
        tok = tok.rstrip("%")
        try:
            v = float(tok)
            if pct:
                v /= 100.0
            vals.append(v)
        except ValueError:
            pass
    return vals


def _near(v, target, tol):
    return abs(v - target) <= tol


def grade(grader: dict, answer: str, points: float = 1.0,
          negative: float = 0.0) -> tuple[float, float, str]:
    """Grade ``answer`` against ``grader`` spec. Returns (awarded, max, verdict)."""
    t = grader["type"]
    pts = float(points)
    neg = float(negative)
    a = answer or ""
    na = norm(a)

    if t == "exact":
        if any(norm(x) in na for x in grader["accept"]):
            return pts, pts, "correct"
        if any(norm(x) in na for x in grader.get("penalty_accept", [])):
            return -neg, pts, "confidently-wrong (penalized)"
        return 0.0, pts, "incorrect"

    if t == "mcq":
        # Accept the letter (A/B/C/D) as a standalone token, or the full option text.
        correct = str(grader["correct"]).lower()
        opts = {k.lower(): v for k, v in grader.get("options", {}).items()}
        letter_hit = re.search(rf"(?<![a-z])\(?{re.escape(correct)}\)?(?![a-z])", na)
        text_hit = opts.get(correct) and norm(opts[correct]) in na
        if letter_hit or text_hit:
            return pts, pts, "correct"
        # Penalize confidently choosing a specific wrong letter.
        for k in opts:
            if k != correct and re.search(rf"(?<![a-z])\(?{re.escape(k)}\)?(?![a-z])", na):
                return -neg, pts, "confidently-wrong (penalized)"
        return 0.0, pts, "incorrect"

    if t == "numeric":
        vals = extract_numbers(a)
        tol = grader.get("tolerance", 1e-6)
        if any(_near(v, grader["target"], tol) for v in vals):
            return pts, pts, "correct"
        for trap in grader.get("penalty_if_numeric_near", []):
            if any(_near(v, trap, tol) for v in vals):
                return -neg, pts, "took-the-bait (penalized)"
        return 0.0, pts, "incorrect"

    if t in ("numeric_multi", "numeric_set"):
        vals = extract_numbers(a)
        targets = grader["targets"]
        tol = grader.get("tolerance", 1e-6)
        hit = sum(1 for tg in targets if any(_near(v, tg, tol) for v in vals))
        return pts * hit / len(targets), pts, f"{hit}/{len(targets)} parts"

    if t == "contains_all":
        terms = grader["terms"]
        for bad in grader.get("penalty_if_contains_any", []):
            if norm(bad) in na:
                return -neg, pts, "took-the-bait (penalized)"
        found = sum(1 for x in terms if norm(x) in na)
        if found == len(terms):
            return pts, pts, "correct"
        if grader.get("allow_partial"):
            return pts * found / len(terms), pts, f"{found}/{len(terms)} terms"
        return 0.0, pts, "incorrect"

    if t == "contains_any":
        if any(norm(x) in na for x in grader["terms"]):
            return pts, pts, "correct"
        return 0.0, pts, "incorrect"

    if t == "regex":
        flags = re.I if grader.get("ignorecase", True) else 0
        if re.search(grader["pattern"], a, flags):
            return pts, pts, "correct"
        return 0.0, pts, "incorrect"

    if t == "flag_false_premise":
        if any(norm(x) in na for x in grader["must_contain_any"]):
            return pts, pts, "flagged the false premise"
        if any(norm(x) in na for x in grader.get("penalty_if_contains_any", [])):
            return -neg, pts, "completed the false 'proof' (penalized)"
        return 0.0, pts, "missed the false premise"

    if t == "abstain":
        markers = ABSTAIN_MARKERS + [m.lower() for m in grader.get("also_accept", [])]
        abstained = any(m in na for m in markers)
        fabricated = any(norm(x) in na for x in grader.get("fabrication_if_contains_any", []))
        if abstained and not fabricated:
            return pts, pts, "honest abstention"
        if fabricated and not abstained:
            return -neg, pts, "hallucinated (penalized)"
        if fabricated and abstained:
            return 0.0, pts, "mixed / hedged fabrication"
        return 0.0, pts, "no clear abstention"

    if t == "rubric_keywords":
        # Soft rubric: award proportional credit for hitting required concepts; a
        # confident wrong claim (penalty term) costs negative marks.
        need = grader["keywords"]
        for bad in grader.get("penalty_if_contains_any", []):
            if norm(bad) in na:
                return -neg, pts, "asserted a disqualifying claim (penalized)"
        found = sum(1 for x in need if norm(x) in na)
        frac = found / len(need) if need else 0.0
        if frac >= grader.get("pass_fraction", 1.0):
            return pts, pts, "meets rubric"
        return round(pts * frac, 3), pts, f"{found}/{len(need)} rubric points"

    if t == "structured_json":
        try:
            obj = json.loads(_extract_json(a))
        except Exception:
            return 0.0, pts, "no parseable JSON"
        want = grader["expect"]
        hit = sum(1 for k, v in want.items() if _json_field_match(obj, k, v))
        frac = hit / len(want) if want else 0.0
        if frac == 1.0:
            return pts, pts, "correct JSON"
        return round(pts * frac, 3), pts, f"{hit}/{len(want)} fields"

    raise ValueError("unknown grader type: " + t)


def _extract_json(text: str) -> str:
    text = text or ""
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


def _json_field_match(obj, key, val) -> bool:
    if not isinstance(obj, dict) or key not in obj:
        return False
    got = obj[key]
    if isinstance(val, (int, float)) and isinstance(got, (int, float)):
        return abs(float(got) - float(val)) <= 1e-6
    return norm(str(got)) == norm(str(val))


# --------------------------------------------------------------------------- #
# Synthetic answer generators — used by tests/demos to drive a simulated model and
# to validate that every generator's grader is satisfiable + that the adversary is
# net-penalized (the Ω selftest contract, generalized to all packs).
# --------------------------------------------------------------------------- #

def synth_good(grader: dict) -> str:
    t = grader["type"]
    if t == "exact":
        return grader["accept"][0]
    if t == "mcq":
        opt = grader.get("options", {}).get(grader["correct"], "")
        return f"The answer is {grader['correct']}. {opt}"
    if t == "numeric":
        return f"After working it through, the answer is {grader['target']}."
    if t in ("numeric_multi", "numeric_set"):
        return "The values are " + ", ".join(str(x) for x in grader["targets"]) + "."
    if t == "contains_all":
        return " ".join(grader["terms"])
    if t == "contains_any":
        return grader["terms"][0]
    if t == "regex":
        return grader.get("example", "")
    if t == "flag_false_premise":
        return "Stop — " + grader["must_contain_any"][0] + ", so the premise is false."
    if t == "abstain":
        extra = (" " + grader.get("also_accept", [""])[0]) if grader.get("also_accept") else ""
        return ("I cannot find any record of this; it does not exist and appears to be "
                "fictional." + extra)
    if t == "rubric_keywords":
        return " ".join(grader["keywords"])
    if t == "structured_json":
        return json.dumps(grader["expect"])
    return ""


def synth_bad(grader: dict) -> str:
    t = grader["type"]
    if t == "exact":
        pa = grader.get("penalty_accept")
        return pa[0] if pa else "purple monkey dishwasher"
    if t == "mcq":
        wrong = [k for k in grader.get("options", {}) if k != grader["correct"]]
        return f"Clearly the answer is {wrong[0]}." if wrong else "definitely Z"
    if t == "numeric":
        trap = grader.get("penalty_if_numeric_near")
        return f"The answer is clearly {trap[0]}." if trap else "The answer is 99999."
    if t in ("numeric_multi", "numeric_set"):
        return "I think it is 1 and 1."
    if t == "contains_all":
        bad = grader.get("penalty_if_contains_any")
        return bad[0] if bad else "completely unrelated text"
    if t == "contains_any":
        return "completely unrelated text"
    if t == "regex":
        return "completely unrelated text"
    if t == "flag_false_premise":
        bad = grader.get("penalty_if_contains_any")
        return ("Sure. " + bad[0]) if bad else "Sure, here is the proof, no objections. QED"
    if t == "abstain":
        fab = grader.get("fabrication_if_contains_any")
        return (fab[0] + " — and here is a great deal of confident detail.") if fab \
            else "Yes, absolutely, here are the confident details."
    if t == "rubric_keywords":
        bad = grader.get("penalty_if_contains_any")
        return bad[0] if bad else "irrelevant assertion"
    if t == "structured_json":
        return "{}"
    return "wrong"
