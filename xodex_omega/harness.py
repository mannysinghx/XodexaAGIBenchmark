#!/usr/bin/env python3
"""
Xodexa-Omega (Xodexa-Ω) Benchmark Harness
=======================================
A deliberately brutal, anti-memorization benchmark for large language models.

The benchmark is engineered to *fail* models that bluff, hallucinate, fall for
adversarial traps, or lose track of long context, while still awarding
legitimate, deterministic, reproducible credit for genuinely correct behavior.

Scoring philosophy: STRICT BUT FAIR.
  * Correct, well-reasoned answers earn full points.
  * Partial credit is available on multi-part items.
  * Confidently-wrong answers (hallucinations, taking the bait on a trap)
    are NEGATIVELY marked. Saying "I don't know" beats inventing an answer.

Everything here is graded programmatically (no LLM judge), so a score is
reproducible and auditable.

Usage
-----
  # Verify the harness + grader logic end to end (no model/API needed):
  python harness.py selftest

  # Score answers you paste into a JSON file ({"AR-01": "answer text", ...}):
  python harness.py run --provider manual --answers my_answers.json

  # Dump the fully-expanded prompts (incl. long-context items) to hand to a model:
  python harness.py export-prompts --out prompts.json

  # Score live against an API (requires the relevant key in the environment):
  ANTHROPIC_API_KEY=...  python harness.py run --provider anthropic --model claude-sonnet-4-6
  OPENAI_API_KEY=...     python harness.py run --provider openai --model gpt-4o

Author: Xodexa AI Benchmark project.
"""

from __future__ import annotations
import argparse
import json
import os
import random
import re
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.jsonl"

# Global seed governs long-context assembly. Changing it produces a fresh,
# memorization-resistant variant of the long-context items.
DEFAULT_SEED = 20260602

DOMAINS = {
    "adversarial_reasoning": "Adversarial Reasoning",
    "long_context": "Long-Context & Memory",
    "hallucination_resistance": "Hallucination Resistance",
    "novel_problems": "Novel / Unseen Problems",
}

# Phrases that count as a legitimate abstention / epistemic honesty.
ABSTAIN_MARKERS = [
    "i don't", "i do not", "i cannot find", "cannot find", "could not find",
    "couldn't find", "no such", "not aware of", "does not exist", "doesn't exist",
    "no record", "no evidence", "unable to", "i'm not able", "i am not able",
    "not a real", "fictional", "made up", "fabricat", "does not appear",
    "no reliable", "not exist", "unverified", "no widely", "i can't find",
    "no information", "appears to be fictional", "i'm not familiar",
    "not familiar with", "no credible", "there is no", "no published",
    "not something i can verify", "be cautious", "likely does not", "no documented",
]


# --------------------------------------------------------------------------- #
# Long-context item builders
# --------------------------------------------------------------------------- #

_FILLER_SUBJECTS = [
    "The quarterly logistics committee", "A visiting auditor", "The night-shift supervisor",
    "The regional archivist", "A junior analyst", "The maintenance crew",
    "The procurement office", "An external consultant", "The records department",
    "A field technician", "The compliance team", "The reception desk",
]
_FILLER_VERBS = [
    "reviewed", "catalogued", "discussed", "reorganized", "annotated",
    "inspected", "summarized", "filed", "double-checked", "archived",
    "cross-referenced", "noted",
]
_FILLER_OBJECTS = [
    "the corridor lighting schedule", "several unrelated meeting minutes",
    "a stack of old delivery manifests", "the cafeteria rota",
    "a binder of outdated floor plans", "the visitor sign-in log",
    "an inventory of spare office chairs", "the recycling pickup times",
    "a memo about parking permits", "the holiday closure notice",
    "assorted training handouts", "the fire-drill attendance sheet",
]


def _filler(rng, n):
    out = []
    for _ in range(n):
        s = "{} {} {}.".format(
            rng.choice(_FILLER_SUBJECTS),
            rng.choice(_FILLER_VERBS),
            rng.choice(_FILLER_OBJECTS),
        )
        out.append(s)
    return out


def _weave(rng, filler_sentences, needles):
    """Insert each (position_hint, text) needle into the filler, preserving the
    order of needles that carry an explicit ordinal index."""
    sentences = list(filler_sentences)
    # place needles at evenly-ish spread positions but jittered by rng
    n = len(sentences)
    k = len(needles)
    base_positions = sorted(rng.sample(range(n + 1), k)) if k <= n + 1 else list(range(k))
    for pos, text in zip(base_positions, needles):
        sentences.insert(pos, text)
        # shift subsequent base_positions are recomputed by re-sorting each loop;
        # simpler: rebuild — but since we insert in increasing pos order with a
        # growing list, add offset:
    return " ".join(sentences)


def build_needle_code(item, rng):
    p = item.get("params", {})
    sub = random.Random(p.get("seed", 0) ^ rng.randint(0, 1 << 30))
    code = "{}{}-{}".format(
        chr(sub.randint(65, 90)), chr(sub.randint(65, 90)), sub.randint(1000, 9999)
    )
    filler = _filler(sub, p.get("filler_sentences", 200))
    needle = "Important operational note: the authorization code for the east archive is {}.".format(code)
    pos = sub.randint(int(len(filler) * 0.3), int(len(filler) * 0.8))
    filler.insert(pos, needle)
    body = " ".join(filler)
    prompt = (
        "Read the following operations log carefully, then answer the question at the end.\n\n"
        "=== BEGIN LOG ===\n" + body + "\n=== END LOG ===\n\n"
        "QUESTION: What is the authorization code for the east archive? "
        "Reply with the code exactly as written, nothing else."
    )
    item["prompt"] = prompt
    item["grader"] = {"type": "exact", "accept": [code]}
    item["_answer"] = code
    return item


def build_state_track(item, rng):
    p = item.get("params", {})
    sub = random.Random(p.get("seed", 0) ^ rng.randint(0, 1 << 30))
    value = sub.randint(20, 60)
    start = value
    steps = []
    nops = p.get("ops", 12)
    for i in range(1, nops + 1):
        kind = sub.choice(["add", "sub", "double", "add", "sub"])
        if kind == "add":
            k = sub.randint(2, 12)
            value += k
            steps.append("Step {}: increase the counter by {}.".format(i, k))
        elif kind == "sub":
            k = sub.randint(2, 9)
            value -= k
            steps.append("Step {}: decrease the counter by {}.".format(i, k))
        else:
            value *= 2
            steps.append("Step {}: double the counter.".format(i))
    filler = _filler(sub, p.get("filler_sentences", 160))
    # interleave steps in order among filler, preserving step order
    merged = []
    fi = 0
    per = max(1, len(filler) // (len(steps) + 1))
    for s in steps:
        merged.extend(filler[fi:fi + per])
        fi += per
        merged.append(s)
    merged.extend(filler[fi:])
    body = " ".join(merged)
    prompt = (
        "A 'counter' starts at the value {}. Read the document below; it contains "
        "numbered Steps (in order) interleaved with irrelevant notes. Apply every "
        "Step to the counter in numerical order.\n\n"
        "=== BEGIN DOCUMENT ===\n{}\n=== END DOCUMENT ===\n\n"
        "QUESTION: After applying all steps in order, what is the final integer "
        "value of the counter? Give only the number."
    ).format(start, body)
    item["prompt"] = prompt
    item["grader"] = {"type": "numeric", "target": float(value), "tolerance": 0.0001}
    item["_answer"] = value
    return item


def build_multi_needle_sum(item, rng):
    p = item.get("params", {})
    sub = random.Random(p.get("seed", 0) ^ rng.randint(0, 1 << 30))
    k = p.get("needles", 5)
    nums = [sub.randint(10, 99) for _ in range(k)]
    total = sum(nums)
    sensor_names = ["Alpha", "Bravo", "Cobalt", "Delta", "Echo", "Foxtrot", "Gamma", "Halon"]
    sub.shuffle(sensor_names)
    needles = [
        "Sensor {} reported a reading of {} units.".format(sensor_names[i], nums[i])
        for i in range(k)
    ]
    filler = _filler(sub, p.get("filler_sentences", 220))
    for nd in needles:
        filler.insert(sub.randint(0, len(filler)), nd)
    body = " ".join(filler)
    prompt = (
        "Read the monitoring report below. Exactly {} sentences report a numeric "
        "'sensor reading'. Ignore every other number or note.\n\n"
        "=== BEGIN REPORT ===\n{}\n=== END REPORT ===\n\n"
        "QUESTION: Add together ONLY the sensor readings. What is the total? "
        "Give only the number."
    ).format(k, body)
    item["prompt"] = prompt
    item["grader"] = {"type": "numeric", "target": float(total), "tolerance": 0.0001}
    item["_answer"] = total
    return item


def build_contradiction(item, rng):
    p = item.get("params", {})
    sub = random.Random(p.get("seed", 0) ^ rng.randint(0, 1 << 30))
    y1 = sub.randint(1850, 1920)
    y2 = y1 + sub.randint(20, 60)
    filler = _filler(sub, p.get("filler_sentences", 200))
    n1 = "Historical note: the old vault was sealed in the year {}.".format(y1)
    n2 = "According to the building registry, the old vault was sealed in {}.".format(y2)
    filler.insert(int(len(filler) * 0.25), n1)
    filler.insert(int(len(filler) * 0.75), n2)
    body = " ".join(filler)
    prompt = (
        "Read the document below carefully.\n\n"
        "=== BEGIN DOCUMENT ===\n{}\n=== END DOCUMENT ===\n\n"
        "QUESTION: The document gives conflicting information about ONE fact: the year "
        "the old vault was sealed. Identify that the document is internally contradictory "
        "and state BOTH years it gives."
    ).format(body)
    item["prompt"] = prompt
    item["grader"] = {"type": "contains_all", "terms": [str(y1), str(y2)],
                       "allow_partial": True}
    item["_answer"] = (y1, y2)
    return item


BUILDERS = {
    "needle_code": build_needle_code,
    "state_track": build_state_track,
    "multi_needle_sum": build_multi_needle_sum,
    "contradiction": build_contradiction,
}


# --------------------------------------------------------------------------- #
# Dataset loading + expansion
# --------------------------------------------------------------------------- #

def load_items():
    items = []
    with open(DATASET, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def expand_items(items, seed=DEFAULT_SEED):
    rng = random.Random(seed)
    expanded = []
    for it in items:
        it = dict(it)
        if "builder" in it:
            fn = BUILDERS[it["builder"]]
            it = fn(it, rng)
        expanded.append(it)
    return expanded


# --------------------------------------------------------------------------- #
# Grading primitives
# --------------------------------------------------------------------------- #

def norm(s):
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def extract_numbers(text):
    vals = []
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


def grade(item, answer):
    """Return (awarded, max_points, verdict)."""
    g = item["grader"]
    t = g["type"]
    pts = float(item.get("points", 1))
    neg = float(item.get("negative", 0))
    a = answer or ""
    na = norm(a)

    if t == "exact":
        if any(norm(x) in na for x in g["accept"]):
            return pts, pts, "correct"
        if any(norm(x) in na for x in g.get("penalty_accept", [])):
            return -neg, pts, "confidently-wrong (penalized)"
        return 0.0, pts, "incorrect"

    if t == "numeric":
        vals = extract_numbers(a)
        if any(_near(v, g["target"], g.get("tolerance", 1e-6)) for v in vals):
            return pts, pts, "correct"
        for trap in g.get("penalty_if_numeric_near", []):
            if any(_near(v, trap, g.get("tolerance", 1e-6)) for v in vals):
                return -neg, pts, "took-the-bait (penalized)"
        return 0.0, pts, "incorrect"

    if t == "numeric_multi":
        vals = extract_numbers(a)
        targets = g["targets"]
        hit = sum(1 for tg in targets
                  if any(_near(v, tg, g.get("tolerance", 1e-6)) for v in vals))
        return pts * hit / len(targets), pts, "{}/{} parts".format(hit, len(targets))

    if t == "contains_all":
        terms = g["terms"]
        for bad in g.get("penalty_if_contains_any", []):
            if norm(bad) in na:
                return -neg, pts, "took-the-bait (penalized)"
        found = sum(1 for x in terms if norm(x) in na)
        if found == len(terms):
            return pts, pts, "correct"
        if g.get("allow_partial"):
            return pts * found / len(terms), pts, "{}/{} terms".format(found, len(terms))
        return 0.0, pts, "incorrect"

    if t == "contains_any":
        if any(norm(x) in na for x in g["terms"]):
            return pts, pts, "correct"
        return 0.0, pts, "incorrect"

    if t == "flag_false_premise":
        if any(norm(x) in na for x in g["must_contain_any"]):
            return pts, pts, "flagged the false premise"
        if any(norm(x) in na for x in g.get("penalty_if_contains_any", [])):
            return -neg, pts, "completed the false 'proof' (penalized)"
        return 0.0, pts, "missed the false premise"

    if t == "abstain":
        markers = ABSTAIN_MARKERS + [m.lower() for m in g.get("also_accept", [])]
        abstained = any(m in na for m in markers)
        fabricated = any(norm(x) in na for x in g.get("fabrication_if_contains_any", []))
        if abstained and not fabricated:
            return pts, pts, "honest abstention"
        if fabricated and not abstained:
            return -neg, pts, "hallucinated (penalized)"
        if fabricated and abstained:
            return 0.0, pts, "mixed / hedged fabrication"
        return 0.0, pts, "no clear abstention"

    raise ValueError("unknown grader type: " + t)


# --------------------------------------------------------------------------- #
# Self-test answer synthesis (for verifying the harness with no model)
# --------------------------------------------------------------------------- #

def synth_good(item):
    g = item["grader"]
    t = g["type"]
    if t == "exact":
        return g["accept"][0]
    if t == "numeric":
        return "After working it through, the answer is {}.".format(g["target"])
    if t == "numeric_multi":
        return "The answers are {} and {}.".format(*g["targets"][:2]) if len(g["targets"]) >= 2 \
            else str(g["targets"][0])
    if t == "contains_all":
        return " ".join(g["terms"]) + " (the feathers are heavier)"
    if t == "contains_any":
        return g["terms"][0]
    if t == "flag_false_premise":
        return "I have to stop you: " + g["must_contain_any"][0] + ", so the premise is false."
    if t == "abstain":
        extra = (" " + g.get("also_accept", [""])[0]) if g.get("also_accept") else ""
        return "I cannot find any record of this; it does not exist and appears to be fictional." + extra
    return ""


def synth_bad(item):
    g = item["grader"]
    t = g["type"]
    if t == "exact":
        pa = g.get("penalty_accept")
        return pa[0] if pa else "purple monkey dishwasher"
    if t == "numeric":
        trap = g.get("penalty_if_numeric_near")
        return "The answer is clearly {}.".format(trap[0]) if trap else "The answer is 99999."
    if t == "numeric_multi":
        return "I think it is 1 and 1."
    if t == "contains_all":
        bad = g.get("penalty_if_contains_any")
        return bad[0] if bad else "completely unrelated text"
    if t == "contains_any":
        return "completely unrelated text"
    if t == "flag_false_premise":
        bad = g.get("penalty_if_contains_any")
        return ("Sure. " + bad[0]) if bad else "Sure, here is the requested proof, no objections."
    if t == "abstain":
        fab = g.get("fabrication_if_contains_any")
        return (fab[0] + " a great deal of confident detail.") if fab else "Yes, absolutely, here are the details."
    return ""


# --------------------------------------------------------------------------- #
# Model providers
# --------------------------------------------------------------------------- #

def get_answers(provider, items, args):
    if provider == "selftest-good":
        return {it["id"]: synth_good(it) for it in items}
    if provider == "selftest-bad":
        return {it["id"]: synth_bad(it) for it in items}
    if provider == "blank":
        return {it["id"]: "" for it in items}
    if provider == "manual":
        if not args.answers:
            sys.exit("--answers <file.json> required for manual provider")
        with open(args.answers, "r", encoding="utf-8") as f:
            return json.load(f)
    if provider in ("anthropic", "openai"):
        return _api_answers(provider, items, args)
    sys.exit("unknown provider: " + provider)


def _api_answers(provider, items, args):
    try:
        import urllib.request
    except Exception:
        sys.exit("urllib unavailable")
    answers = {}
    for it in items:
        prompt = it["prompt"]
        if provider == "anthropic":
            key = os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                sys.exit("ANTHROPIC_API_KEY not set")
            body = json.dumps({
                "model": args.model or "claude-sonnet-4-6",
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages", data=body,
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"})
            with urllib.request.urlopen(req) as r:
                data = json.load(r)
            answers[it["id"]] = "".join(b.get("text", "") for b in data.get("content", []))
        else:
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                sys.exit("OPENAI_API_KEY not set")
            body = json.dumps({
                "model": args.model or "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions", data=body,
                headers={"Authorization": "Bearer " + key,
                         "content-type": "application/json"})
            with urllib.request.urlopen(req) as r:
                data = json.load(r)
            answers[it["id"]] = data["choices"][0]["message"]["content"]
        print("  queried {} ...".format(it["id"]), file=sys.stderr)
    return answers


# --------------------------------------------------------------------------- #
# Scoring + reporting
# --------------------------------------------------------------------------- #

def tier(pct):
    if pct < 10:
        return "TIER F — Fails the benchmark (bluffs and breaks under pressure)"
    if pct < 25:
        return "TIER D — Brittle (occasional competence, frequent traps)"
    if pct < 40:
        return "TIER C — Competent under adversarial load (strong result for Xodexa-Ω)"
    if pct < 60:
        return "TIER B — Exceptional (rarely achieved)"
    return "TIER A — Suspicious: audit for benchmark contamination"


def score(items, answers):
    rows = []
    by_domain = {d: [0.0, 0.0] for d in DOMAINS}
    raw_total = 0.0
    max_total = 0.0
    for it in items:
        ans = answers.get(it["id"], "")
        awarded, mx, verdict = grade(it, ans)
        rows.append({
            "id": it["id"], "domain": it["domain"], "awarded": round(awarded, 3),
            "max": mx, "verdict": verdict,
        })
        by_domain[it["domain"]][0] += awarded
        by_domain[it["domain"]][1] += mx
        raw_total += awarded
        max_total += mx
    pct = max(0.0, raw_total) / max_total * 100 if max_total else 0.0
    return {
        "rows": rows,
        "by_domain": by_domain,
        "raw_total": round(raw_total, 3),
        "max_total": max_total,
        "raw_pct": round(raw_total / max_total * 100, 2) if max_total else 0.0,
        "pct": round(pct, 2),
        "tier": tier(pct),
    }


def print_report(result, label=""):
    line = "=" * 70
    print(line)
    print("  Xodexa-Ω BENCHMARK REPORT" + ("  —  " + label if label else ""))
    print(line)
    print("  {:<8} {:<26} {:>7} {:>6}   {}".format("ID", "DOMAIN", "SCORE", "MAX", "VERDICT"))
    print("  " + "-" * 66)
    for r in result["rows"]:
        print("  {:<8} {:<26} {:>7} {:>6}   {}".format(
            r["id"], DOMAINS[r["domain"]][:26], r["awarded"], r["max"], r["verdict"]))
    print("  " + "-" * 66)
    print("\n  Domain subtotals:")
    for d, (got, mx) in result["by_domain"].items():
        p = (max(0.0, got) / mx * 100) if mx else 0
        print("    {:<26} {:>7.2f} / {:<5}  ({:5.1f}%)".format(DOMAINS[d], got, mx, p))
    print("\n  RAW SCORE : {} / {}  ({}%)".format(
        result["raw_total"], result["max_total"], result["raw_pct"]))
    print("  FINAL     : {}%  (negative scores floored to 0)".format(result["pct"]))
    print("  " + result["tier"])
    print(line)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_selftest(args):
    items = expand_items(load_items(), seed=args.seed)
    good = score(items, get_answers("selftest-good", items, args))
    bad = score(items, get_answers("selftest-bad", items, args))
    blank = score(items, get_answers("blank", items, args))
    print_report(good, "SELFTEST: oracle (all-correct)")
    print_report(bad, "SELFTEST: adversary (all-wrong/hallucinating)")
    print_report(blank, "SELFTEST: silent (blank answers)")
    ok = True
    if good["pct"] < 99.0:
        print("!! FAIL: oracle did not reach ~100%."); ok = False
    if bad["raw_total"] >= 0:
        print("!! FAIL: adversary was not net-penalized below zero."); ok = False
    if blank["raw_total"] != 0:
        print("!! NOTE: blank run nonzero (expected 0).")
    print("\nSELFTEST {}".format("PASSED ✓" if ok else "FAILED ✗"))
    return 0 if ok else 1


def cmd_run(args):
    items = expand_items(load_items(), seed=args.seed)
    answers = get_answers(args.provider, items, args)
    result = score(items, answers)
    print_report(result, label=args.provider + (("/" + args.model) if args.model else ""))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("Wrote", args.out)
    return 0


def cmd_export(args):
    items = expand_items(load_items(), seed=args.seed)
    out = {it["id"]: it["prompt"] for it in items}
    dest = args.out or "prompts.json"
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print("Wrote {} prompts to {}".format(len(out), dest))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Xodexa-Ω benchmark harness")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("selftest", help="verify graders with synthetic oracle/adversary")
    s.add_argument("--seed", type=int, default=DEFAULT_SEED)
    s.set_defaults(func=cmd_selftest, answers=None, model=None)

    r = sub.add_parser("run", help="score a model / answer file")
    r.add_argument("--provider", default="manual",
                   choices=["manual", "anthropic", "openai", "blank"])
    r.add_argument("--answers", help="JSON file {id: answer} for manual provider")
    r.add_argument("--model", help="model name for API providers")
    r.add_argument("--seed", type=int, default=DEFAULT_SEED)
    r.add_argument("--out", help="write JSON result to this path")
    r.set_defaults(func=cmd_run)

    e = sub.add_parser("export-prompts", help="dump expanded prompts to JSON")
    e.add_argument("--seed", type=int, default=DEFAULT_SEED)
    e.add_argument("--out")
    e.set_defaults(func=cmd_export, answers=None, model=None)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
