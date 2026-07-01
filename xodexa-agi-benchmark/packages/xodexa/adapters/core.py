"""
xodexa.adapters.core
======================
The two ingest modes and their shared invariant, plus a pure file-dispatch helper.

Everything a caller mints through this module is stamped comparison-mode
(:data:`COMPARISON_STAMP`) so it can never be confused with an official Xodexa Score.
The stamp is applied last and unconditionally on every return path; the adapter tests
assert ``official is False`` and ``mode == "comparison"`` on all of them, which is the
single guard that keeps external results off the official leaderboard.

  * :func:`central_rescore` — MODE A. Reshaped external raw outputs → the real central
    grader (``evaluate.score_pack``). Real scoring, but comparison-mode because Xodexa
    didn't control inference.
  * :func:`anchor_result` — MODE B. A native benchmark metric → a normalized 0..1
    entry via ``anchors.normalize_score``, carrying its contamination-risk label.
  * :func:`ingest_file` — read a JSON file and dispatch to one of the above by ``fmt``.
"""

from __future__ import annotations

import json
from typing import Any

from .. import anchors, evaluate
from .lm_eval import parse_lm_eval_raw
from .inspect_ai import parse_inspect_log

# The invariant. Applied last on every return path so no code branch can forget it.
COMPARISON_STAMP = {"official": False, "mode": "comparison"}


def _stamp(d: dict) -> dict:
    """Force the comparison-mode invariant onto a result dict (last word wins)."""
    d.update(COMPARISON_STAMP)
    return d


# --------------------------------------------------------------------------- #
# MODE A — raw-output central re-score
# --------------------------------------------------------------------------- #

def central_rescore(answer_keys: dict, external_responses: list[dict],
                    source: str) -> dict:
    """Re-score externally-captured raw outputs with Xodexa's central grader.

    ``answer_keys`` is ``{task_id: schema.answer_key(task)}`` (server-side keys).
    ``external_responses`` is the ``responses`` list produced by one of the parsers
    (``parse_lm_eval_raw`` / ``parse_inspect_log``): ``[{"id","output", ...}]``.
    ``source`` is a free-text provenance label (e.g. ``"lm-eval-harness"``).

    Returns the full ``evaluate.score_pack`` result, stamped comparison-mode with
    ``scoring == "central-re-score"`` and the source echoed back. This is the strong
    path: the grade is real, only the inference loop was external.
    """
    result = evaluate.score_pack(answer_keys, external_responses)
    result["source"] = source
    result["scoring"] = "central-re-score"
    return _stamp(result)


# --------------------------------------------------------------------------- #
# MODE B — native-metric anchor
# --------------------------------------------------------------------------- #

def anchor_result(anchor_key: str, native_value: float, n_items: int,
                  source: str) -> dict:
    """Normalize an external benchmark's native metric into a comparison entry.

    ``anchor_key`` must be a registered anchor (see ``anchors.ANCHORS``); an unknown
    key raises ``KeyError`` with the list of valid keys. ``native_value`` is the
    benchmark's own metric value (e.g. 72.0 for 72% accuracy), ``n_items`` the sample
    count behind it, ``source`` a provenance label (e.g. ``"paper"``).

    Returns the anchor metadata plus the normalized 0..1 value and its
    contamination-risk label, stamped comparison-mode.
    """
    if anchor_key not in anchors.ANCHORS:
        raise KeyError(
            f"unknown anchor_key {anchor_key!r}; valid keys: "
            f"{sorted(anchors.ANCHORS)}"
        )
    a = anchors.ANCHORS[anchor_key]
    return _stamp({
        "anchor": a.key,
        "name": a.name,
        "dimension": a.dimension,
        "native_metric": a.metric,
        "native_value": native_value,
        "normalized_0_1": anchors.normalize_score(anchor_key, native_value),
        "n_items": n_items,
        "contamination_risk": a.contamination_risk,
        "license": a.license,
        "source": source,
    })


# --------------------------------------------------------------------------- #
# File dispatch (importable + pure)
# --------------------------------------------------------------------------- #

def ingest_file(path: str, fmt: str, *, answer_keys: dict | None = None,
                id_map: dict | None = None, source: str | None = None,
                anchor_key: str | None = None, native_value: float | None = None,
                n_items: int | None = None) -> dict:
    """Read a JSON file at ``path`` and dispatch by ``fmt``.

    ``fmt`` is one of:

      * ``"lm-eval-raw"`` — parse the file as lm-eval samples and MODE-A re-score.
        Requires ``answer_keys``; ``id_map`` optional.
      * ``"inspect-log"`` — parse the file as an Inspect eval log and MODE-A re-score.
        Requires ``answer_keys``; ``id_map`` optional.
      * ``"anchor"`` — MODE B. The file may supply ``anchor_key`` / ``native_value`` /
        ``n_items`` (explicit args override the file's values).

    Pure: no argparse, no stdout, no network — just read + dispatch. ``source``
    defaults to ``"file:<path>"``.
    """
    with open(path, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    src = source or f"file:{path}"

    if fmt == "lm-eval-raw":
        if answer_keys is None:
            raise ValueError("fmt='lm-eval-raw' requires answer_keys for central re-score")
        responses = parse_lm_eval_raw(obj, id_map=id_map)
        return central_rescore(answer_keys, responses, source=src)

    if fmt == "inspect-log":
        if answer_keys is None:
            raise ValueError("fmt='inspect-log' requires answer_keys for central re-score")
        responses = parse_inspect_log(obj, id_map=id_map)
        return central_rescore(answer_keys, responses, source=src)

    if fmt == "anchor":
        # File may carry the anchor payload; explicit kwargs take precedence.
        payload: dict[str, Any] = obj if isinstance(obj, dict) else {}
        key = anchor_key or payload.get("anchor_key") or payload.get("anchor")
        val = native_value if native_value is not None else payload.get("native_value")
        n = n_items if n_items is not None else payload.get("n_items", 0)
        if key is None or val is None:
            raise ValueError("fmt='anchor' requires anchor_key and native_value "
                             "(via args or in the file)")
        return anchor_result(key, float(val), int(n), source=src)

    raise ValueError(f"unknown fmt {fmt!r}; expected one of "
                     "'lm-eval-raw', 'inspect-log', 'anchor'")


if __name__ == "__main__":  # pragma: no cover - illustrative demo, not a CLI contract
    # Minimal demo of MODE B against a real anchor, and MODE A on a hand-built pack.
    print("MODE B demo:", anchor_result("mmlu_pro", 72.0, 100, "demo"))

    from .. import schema
    from ..generators import generate_from

    tasks = generate_from("code.exec_filter_fold", 2, seed=1)
    keys = {t.task_id: schema.answer_key(t) for t in tasks}
    # Craft a fake lm-eval object whose records embed the Xodexa id + a good output.
    from .. import grade
    records = [{"doc_id": i, "xodexa_task_id": t.task_id,
                "filtered_resps": [grade.synth_good(schema.answer_key(t)["grader"])]}
               for i, t in enumerate(tasks)]
    responses = parse_lm_eval_raw(records)
    print("MODE A demo:", central_rescore(keys, responses, "demo")["frontier_metrics"])
