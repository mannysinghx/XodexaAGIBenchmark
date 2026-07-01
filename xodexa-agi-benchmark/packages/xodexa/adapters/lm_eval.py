"""
xodexa.adapters.lm_eval
=========================
MODE A parser for EleutherAI's **lm-evaluation-harness** raw output.

Why an explicit id contract is unavoidable: lm-eval identifies samples by its own
``doc_id`` (an integer row index into whatever HF dataset the task loaded), which has
no relationship to a Xodexa ``task_id`` (a content hash). We therefore cannot silently
join the two — that would misgrade every item. This adapter supports the two only
honest ways to bridge them:

  1. **Embedded id** (preferred). If the operator seeded the pack through lm-eval as a
     custom task, each doc should carry the Xodexa id in a known field. We look for
     ``xodexa_task_id`` on the record, then on its nested ``doc``/``arguments``.
  2. **Explicit ``id_map``**. A caller-supplied ``{lm_eval_key: xodexa_task_id}`` map,
     where the lm-eval key is the record's ``doc_id`` (or ``id``). Records whose key
     is absent from the map are dropped (they aren't Xodexa tasks).

Record shape we accept (lm-eval ``--log_samples`` JSONL rows, or the ``samples`` lists
inside a full results object). We read, in order of preference for the model text:

  * ``record["filtered_resps"]`` — post-filter final responses (list; we take [0]);
  * ``record["resps"]``          — raw responses, possibly nested ``[[text]]``;
  * ``record["output"]`` / ``record["response"]`` — flat convenience fields.

And for the id: ``record["xodexa_task_id"]`` › ``record["doc"]["xodexa_task_id"]`` ›
``id_map[str(record["doc_id"])]`` › ``id_map[str(record["id"])]``.

Output: the ``responses`` list ``evaluate.score_pack`` expects — ``{"id","output"}``
per item (confidence/latency/tokens/error left unset; the central grader treats them
as optional). Confidence is passed through when the record carries one.
"""

from __future__ import annotations

from typing import Any


def _first(x: Any) -> Any:
    """Unwrap lm-eval's arbitrarily-nested response containers to a leaf string."""
    while isinstance(x, (list, tuple)) and x:
        x = x[0]
    return x


def _extract_output(record: dict) -> str:
    for field in ("filtered_resps", "resps", "output", "response", "completion"):
        if field in record and record[field] not in (None, [], ""):
            return str(_first(record[field]))
    return ""


def _extract_confidence(record: dict) -> float | None:
    for field in ("confidence", "xodexa_confidence"):
        v = record.get(field)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
    doc = record.get("doc")
    if isinstance(doc, dict) and doc.get("xodexa_confidence") is not None:
        try:
            return float(doc["xodexa_confidence"])
        except (TypeError, ValueError):
            return None
    return None


def _resolve_id(record: dict, id_map: dict | None) -> str | None:
    # 1) embedded id on the record or its nested doc/arguments.
    if record.get("xodexa_task_id"):
        return str(record["xodexa_task_id"])
    for nest in ("doc", "arguments"):
        sub = record.get(nest)
        if isinstance(sub, dict) and sub.get("xodexa_task_id"):
            return str(sub["xodexa_task_id"])
    # 2) explicit id_map keyed by lm-eval's native doc_id / id.
    if id_map:
        for key_field in ("doc_id", "id"):
            if key_field in record:
                mapped = id_map.get(str(record[key_field]))
                if mapped is not None:
                    return str(mapped)
    return None


def _records(results_obj: Any) -> list[dict]:
    """Accept a JSONL-style list of records, or a full lm-eval results object whose
    ``samples`` maps task-name -> list-of-records (we flatten every task)."""
    if isinstance(results_obj, list):
        return [r for r in results_obj if isinstance(r, dict)]
    if isinstance(results_obj, dict):
        samples = results_obj.get("samples")
        if isinstance(samples, dict):
            out: list[dict] = []
            for recs in samples.values():
                if isinstance(recs, list):
                    out.extend(r for r in recs if isinstance(r, dict))
            return out
        if isinstance(samples, list):
            return [r for r in samples if isinstance(r, dict)]
    return []


def parse_lm_eval_raw(results_obj: Any, id_map: dict | None = None) -> list[dict]:
    """Map lm-eval-harness per-sample records to Xodexa ``responses``.

    ``results_obj`` may be a list of sample records or a full results object with a
    ``samples`` field. ``id_map`` optionally maps lm-eval ``doc_id``/``id`` -> Xodexa
    ``task_id``; it is only consulted when a record carries no embedded
    ``xodexa_task_id``. Records that resolve to no Xodexa id are dropped.
    """
    responses: list[dict] = []
    for record in _records(results_obj):
        tid = _resolve_id(record, id_map)
        if tid is None:
            continue
        resp: dict = {"id": tid, "output": _extract_output(record)}
        conf = _extract_confidence(record)
        if conf is not None:
            resp["confidence"] = conf
        responses.append(resp)
    return responses
