"""
xodexa.sandbox
================
Resource-limited execution of model-written Python against HIDDEN unit tests — the
grader the code family always documented ("in a full deployment these would map onto
hidden unit tests") but never had. Code either passes the tests or it does not; no
keyword matching.

Isolation model (honest scope):
  * ``python -I -E -S`` — isolated mode: no site-packages, no env hooks, no cwd on
    sys.path, so the model's code cannot import project internals or user packages.
  * rlimits (best-effort, POSIX): CPU seconds, address space, file size, no core
    dumps. Applied in the child before exec.
  * wall-clock timeout with process kill.
  * NOT a network namespace — full egress isolation needs the containerized runner
    (docker-compose worker); this module is the in-process grader used by tests,
    dev runs, and the sandboxed CI lane. The limitation is deliberate and documented
    rather than pretended away.

Determinism: the harness script seeds nothing and timestamps nothing; verdicts are
pure functions of (code, tests) up to resource-exhaustion boundaries.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass

DEFAULT_TIMEOUT_S = 8.0
DEFAULT_MEMORY_MB = 256
DEFAULT_CPU_S = 5

_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S | re.I)


def extract_code(answer: str) -> str:
    """Pull the model's code out of an answer: prefer the largest fenced python
    block; fall back to the raw text (models often answer with bare code)."""
    answer = answer or ""
    blocks = _FENCE_RE.findall(answer)
    if blocks:
        return max(blocks, key=len).strip()
    return answer.strip()


def _limits_preexec(memory_mb: int, cpu_s: int):
    """Child-side rlimits. Best-effort: any single limit failing (platform quirks,
    e.g. RLIMIT_AS on macOS) must not block execution — the wall-clock kill is the
    backstop."""
    def apply():
        try:
            import resource
        except ImportError:  # non-POSIX
            return
        for lim, val in (
            ("RLIMIT_CPU", (cpu_s, cpu_s + 1)),
            ("RLIMIT_AS", (memory_mb * 1024 * 1024,) * 2),
            ("RLIMIT_FSIZE", (1024 * 1024,) * 2),   # 1 MiB of file writes, max
            ("RLIMIT_CORE", (0, 0)),
        ):
            try:
                resource.setrlimit(getattr(resource, lim), val)
            except (ValueError, OSError, AttributeError):
                pass
    return apply


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool


def run_python(code: str, timeout_s: float = DEFAULT_TIMEOUT_S,
               memory_mb: int = DEFAULT_MEMORY_MB, cpu_s: int = DEFAULT_CPU_S) -> ExecResult:
    """Run ``code`` in an isolated interpreter with resource limits."""
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-E", "-S", "-c", code],
            capture_output=True, text=True, timeout=timeout_s,
            preexec_fn=_limits_preexec(memory_mb, cpu_s) if sys.platform != "win32" else None,
        )
        return ExecResult(proc.stdout, proc.stderr, proc.returncode, False)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        return ExecResult(out, err, -1, True)


_HARNESS = """
import json as _j
_results = []
try:
{indented_code}
except Exception as _e:
    print(_j.dumps({{"fatal": "define: %s: %s" % (type(_e).__name__, _e)}}))
    raise SystemExit(0)
for _t in {tests_json}:
    try:
        _got = {func_name}(*_t["args"])
        _results.append({{"ok": _got == _t["expect"], "got": repr(_got)[:200]}})
    except Exception as _e:
        _results.append({{"ok": False, "error": ("%s: %s" % (type(_e).__name__, _e))[:200]}})
print(_j.dumps({{"results": _results}}))
"""


def run_hidden_tests(model_code: str, func_name: str, tests: list[dict],
                     timeout_s: float = DEFAULT_TIMEOUT_S) -> dict:
    """Execute ``model_code`` and call ``func_name`` against hidden tests.

    tests: [{"args": [...], "expect": <value>}, ...] — expectations compare with ==
    inside the child (so lists/dicts/ints/strs all work; floats should be avoided or
    pre-rounded by the generator).

    Returns {passed, total, verdicts, fatal, timed_out}.
    """
    code = extract_code(model_code)
    if not code:
        return {"passed": 0, "total": len(tests), "verdicts": [],
                "fatal": "no code found in answer", "timed_out": False}
    indented = "\n".join("    " + ln for ln in code.splitlines()) or "    pass"
    script = _HARNESS.format(indented_code=indented,
                             tests_json=json.dumps(tests),
                             func_name=func_name)
    res = run_python(script, timeout_s=timeout_s)
    if res.timed_out:
        return {"passed": 0, "total": len(tests), "verdicts": [],
                "fatal": "timed out", "timed_out": True}
    # The harness prints exactly one JSON line last; tolerate the model's own prints.
    payload = None
    for line in reversed(res.stdout.strip().splitlines()):
        try:
            payload = json.loads(line)
            break
        except ValueError:
            continue
    if not isinstance(payload, dict):
        return {"passed": 0, "total": len(tests), "verdicts": [],
                "fatal": f"no harness output (exit {res.exit_code}; "
                         f"stderr: {res.stderr[:200]})", "timed_out": False}
    if "fatal" in payload:
        return {"passed": 0, "total": len(tests), "verdicts": [],
                "fatal": payload["fatal"], "timed_out": False}
    verdicts = payload.get("results", [])
    return {"passed": sum(1 for v in verdicts if v.get("ok")), "total": len(tests),
            "verdicts": verdicts, "fatal": None, "timed_out": False}
