"""
xodexa.adapters.inspect_ai
============================
MODE A parser for **Inspect AI** eval logs (the ``.eval`` / ``.json`` log an Inspect
run writes, or its in-memory ``EvalLog`` deserialized to a dict).

Why the id story is simpler here than for lm-eval: an Inspect ``Sample`` carries a
first-class ``id`` field that the dataset author controls. When the operator loads a
Xodexa pack as an Inspect dataset, that ``id`` should be the Xodexa ``task_id`` — so
no id_map is usually needed. We still accept a ``metadata.xodexa_task_id`` override and
an explicit ``id_map`` for the case where the sample ``id`` is something else.

Sample shape we read (``eval_log["samples"][i]``):

  * id:      ``sample["id"]`` (preferred) or ``sample["metadata"]["xodexa_task_id"]``,
             optionally remapped through ``id_map``.
  * output:  ``sample["output"]["completion"]`` (Inspect's convenience field) ›
             the last assistant message in ``sample["output"]["choices"][0]["message"]``
             › the last assistant turn in ``sample["messages"]`` › a flat
             ``sample["output"]`` string.
  * confidence (optional): ``sample["metadata"]["xodexa_confidence"]``.

Output: the ``responses`` list ``evaluate.score_pack`` expects — ``{"id","output"}``
(plus ``confidence`` when present). Inspect's own scores are ignored on purpose: this
is a CENTRAL re-score, so only the raw model text crosses the boundary.
"""

from __future__ import annotations

from typing import Any


def _message_text(msg: Any) -> str:
    """An Inspect ``ChatMessage`` is a dict with ``role`` and ``content``; content is a
    string or a list of content parts each carrying ``text``."""
    if isinstance(msg, str):
        return msg
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict) and "text" in p:
                parts.append(str(p["text"]))
            elif isinstance(p, str):
                parts.append(p)
        return "".join(parts)
    return ""


def _last_assistant(messages: Any) -> str:
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                return _message_text(msg)
    return ""


def _extract_output(sample: dict) -> str:
    out = sample.get("output")
    if isinstance(out, dict):
        if out.get("completion"):
            return str(out["completion"])
        choices = out.get("choices")
        if isinstance(choices, list) and choices:
            msg = choices[0].get("message") if isinstance(choices[0], dict) else None
            text = _message_text(msg)
            if text:
                return text
    elif isinstance(out, str) and out:
        return out
    # Fall back to the transcript's last assistant turn.
    return _last_assistant(sample.get("messages"))


def _resolve_id(sample: dict, id_map: dict | None) -> str | None:
    meta = sample.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("xodexa_task_id"):
        return str(meta["xodexa_task_id"])
    sid = sample.get("id")
    if sid is not None:
        if id_map and str(sid) in id_map:
            return str(id_map[str(sid)])
        return str(sid)
    return None


def _extract_confidence(sample: dict) -> float | None:
    meta = sample.get("metadata") or {}
    if isinstance(meta, dict) and meta.get("xodexa_confidence") is not None:
        try:
            return float(meta["xodexa_confidence"])
        except (TypeError, ValueError):
            return None
    return None


def _samples(eval_log_obj: Any) -> list[dict]:
    if isinstance(eval_log_obj, dict):
        samples = eval_log_obj.get("samples")
        if isinstance(samples, list):
            return [s for s in samples if isinstance(s, dict)]
    if isinstance(eval_log_obj, list):
        return [s for s in eval_log_obj if isinstance(s, dict)]
    return []


def parse_inspect_log(eval_log_obj: Any, id_map: dict | None = None) -> list[dict]:
    """Map an Inspect AI eval log's ``samples[]`` to Xodexa ``responses``.

    ``eval_log_obj`` may be the full eval-log dict (with a ``samples`` list) or the
    ``samples`` list itself. ``id_map`` optionally remaps the Inspect sample ``id`` to
    a Xodexa ``task_id``; a ``metadata.xodexa_task_id`` always wins over both. Samples
    that resolve to no id are dropped.
    """
    responses: list[dict] = []
    for sample in _samples(eval_log_obj):
        tid = _resolve_id(sample, id_map)
        if tid is None:
            continue
        resp: dict = {"id": tid, "output": _extract_output(sample)}
        conf = _extract_confidence(sample)
        if conf is not None:
            resp["confidence"] = conf
        responses.append(resp)
    return responses
