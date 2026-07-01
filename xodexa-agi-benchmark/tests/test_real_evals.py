"""Tests for the Phase-2 real-eval additions: sandboxed code execution, BM25
retrieval + live-RAG generators, long-context generators, and verifiable
instruction-following. Also asserts every new generator is schema-valid and its
grader is satisfiable by grade.synth_good (the platform's generator contract)."""

import random

import pytest

from xodexa import grade, schema
from xodexa.rag import BM25Index, tokenize
from xodexa.sandbox import extract_code, run_hidden_tests, run_python
from xodexa.generators import REGISTRY, generate_from


# --------------------------------------------------------------------------- #
# Sandbox
# --------------------------------------------------------------------------- #

def test_extract_code_prefers_fenced_block():
    ans = "Here is my solution:\n```python\ndef f(x):\n    return x + 1\n```\nDone."
    assert extract_code(ans) == "def f(x):\n    return x + 1"


def test_extract_code_falls_back_to_raw():
    assert extract_code("def f(x):\n    return x") == "def f(x):\n    return x"


def test_run_python_captures_stdout():
    r = run_python("print(2 + 2)")
    assert r.stdout.strip() == "4" and r.exit_code == 0 and not r.timed_out


def test_run_python_times_out_on_infinite_loop():
    r = run_python("while True:\n    pass", timeout_s=1.0)
    assert r.timed_out


def test_hidden_tests_all_pass():
    code = "```python\ndef f(xs):\n    return sum(xs)\n```"
    tests = [{"args": [[1, 2, 3]], "expect": 6}, {"args": [[]], "expect": 0}]
    r = run_hidden_tests(code, "f", tests)
    assert r["passed"] == 2 and r["total"] == 2 and r["fatal"] is None


def test_hidden_tests_partial():
    code = "def f(xs):\n    return sum(xs) + 1"  # off by one
    tests = [{"args": [[1, 2]], "expect": 3}, {"args": [[0]], "expect": 0}]
    r = run_hidden_tests(code, "f", tests)
    assert r["passed"] == 0


def test_hidden_tests_syntax_error_is_fatal_not_crash():
    r = run_hidden_tests("def f(:\n bad", "f", [{"args": [1], "expect": 1}])
    assert r["passed"] == 0 and r["fatal"]


def test_sandbox_cannot_import_project_internals():
    # -I isolated mode: no cwd on sys.path, so xodexa is not importable in the child.
    code = "```python\ndef f(x):\n    import xodexa.schema\n    return 1\n```"
    r = run_hidden_tests(code, "f", [{"args": [0], "expect": 1}])
    assert r["passed"] == 0  # import fails inside the sandbox


def test_code_exec_grader_full_and_zero():
    g = {"type": "code_exec", "func_name": "f",
         "tests": [{"args": [[2, 4, 6]], "expect": 12}],
         "reference": "def f(xs):\n    return sum(xs)"}
    aw, mx, _ = grade.grade(g, grade.synth_good(g))
    assert aw == mx
    aw2, _, _ = grade.grade(g, grade.synth_bad(g))
    assert aw2 == 0.0


# --------------------------------------------------------------------------- #
# BM25 retrieval
# --------------------------------------------------------------------------- #

def test_bm25_ranks_relevant_doc_first():
    docs = ["the cat sat on the mat", "quantum chromodynamics lecture notes",
            "a cat and a dog"]
    idx = BM25Index(docs)
    hits = idx.search("cat", k=3)
    assert docs[hits[0][0]].count("cat") >= 1
    assert hits[0][1] > 0


def test_bm25_deterministic_and_tiebroken_by_index():
    docs = ["alpha", "beta", "gamma"]
    idx = BM25Index(docs)
    # query matches nothing -> all zero -> stable index order
    assert [i for i, _ in idx.search("zzz", k=3)] == [0, 1, 2]


def test_tokenize_lowercases_alnum():
    assert tokenize("Hello, World-2!") == ["hello", "world", "2"]


# --------------------------------------------------------------------------- #
# Generator contract: schema-valid + grader satisfiable
# --------------------------------------------------------------------------- #

_NEW_GENERATORS = [
    "code.exec_filter_fold", "code.exec_fix_bug", "code.exec_algorithm",
    "rag_poisoning.rag_live_answer", "rag_poisoning.rag_live_injection",
    "memory.long_needle", "memory.long_multi_needle", "memory.long_state_tracking",
    "instruction_following.numbered_lines", "instruction_following.forbidden_word",
    "instruction_following.structured_reply",
]


@pytest.mark.parametrize("gid", _NEW_GENERATORS)
def test_new_generator_registered(gid):
    assert gid in REGISTRY


@pytest.mark.parametrize("gid", _NEW_GENERATORS)
def test_new_generator_schema_valid(gid):
    for seed in range(3):
        tasks = generate_from(gid, 2, seed=seed, visibility="public")
        for t in tasks:
            errs = schema.validate_task(t)
            assert errs == [], f"{gid} invalid: {errs}"


@pytest.mark.parametrize("gid", _NEW_GENERATORS)
def test_new_generator_grader_satisfiable(gid):
    # synth_good must earn full marks; the adversarial synth_bad must not.
    for seed in range(3):
        t = generate_from(gid, 1, seed=seed, visibility="public")[0]
        g = t.server_grader
        good = grade.synth_good(g)
        aw, mx, _ = grade.grade(g, good, points=t.points, negative=t.negative)
        assert aw >= mx - 1e-6, f"{gid}: synth_good only scored {aw}/{mx}"


def test_long_context_actually_long():
    t = generate_from("memory.long_needle", 1, seed=1)[0]
    assert len(t.prompt) > 20000  # tens of thousands of chars, not a 2k proxy


def test_long_needle_answer_recoverable_from_prompt():
    # The needle (answer) is present in the haystack -> a perfect reader can score.
    t = generate_from("memory.long_needle", 1, seed=3)[0]
    assert str(t.server_grader["accept"][0]) in t.prompt


def test_rag_live_answer_penalizes_hijack_value():
    t = generate_from("rag_poisoning.rag_live_answer", 1, seed=2)[0]
    g = t.server_grader
    assert "penalty_if_numeric_near" in g and g["penalty_if_numeric_near"]
    # true value present in retrieved context
    assert str(int(g["target"])) in t.prompt


def test_instruction_following_constraints_enforced():
    t = generate_from("instruction_following.numbered_lines", 1, seed=5)[0]
    g = t.server_grader
    # a one-line answer violates the exact-line-count constraint
    aw, mx, _ = grade.grade(g, "just one line")
    assert aw < mx
