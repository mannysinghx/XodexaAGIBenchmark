"""
apps.worker.run_job
=====================
Executes a web-initiated benchmark run against a REAL model, end to end:

  resolve key (saved credential → decrypt, or use-once key passed in) → generate a
  fresh seeded pack → call the provider per task (raw outputs) → persist every response
  + a hash-chained event → central re-score (xodexa.evaluate) → signed report
  (xodexa.report) → persist scores/report/leaderboard fields → mark scored.

Runs as an RQ job (Redis) in production, or inline (dev) — same function either way.
No secrets are logged. Per-task provider errors are recorded; an auth-class failure
aborts the run cleanly as 'failed'.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time

from apps.server import providers, security
from apps.server.db import session
from apps.server.models import (ProviderCredential, Report, RunEvent, WebRun,
                                WebRunItemScore, WebRunResponse)

from xodexa import generators as G, schema, evaluate, report as report_mod
from xodexa.crypto import sha256_hex, canonical
from xodexa.runner import usage_breakdown

logger = logging.getLogger("xodexa.run")


def providers_usage_breakdown(conn):
    """(prompt, completion, total) real token counts from the connector's last call, if
    the provider reported usage; any may be None (caller falls back to an estimate)."""
    return usage_breakdown(getattr(conn, "last_usage", None))

# Confidence elicitation: ask the model to state how sure it is, so we can compute
# calibration (RMS-CE) on real runs. The number is parsed out AND stripped from the
# gradeable text so it can't pollute numeric/keyword grading.
CONFIDENCE_INSTRUCTION = (
    "\n\nFinally, on a new line, output exactly: Confidence: N — where N is an integer "
    "from 0 to 100 estimating the probability that your answer above is correct."
)
_CONF_RE = re.compile(r"confidence\s*[:=]\s*(\d{1,3})\s*%?", re.IGNORECASE)


def parse_confidence(text: str):
    """Return (cleaned_text, confidence_0to1_or_None). Removes the matched
    'Confidence: N' mention from the text so grading sees only the answer."""
    if not text:
        return text, None
    matches = list(_CONF_RE.finditer(text))
    if not matches:
        return text, None
    m = matches[-1]
    val = max(0, min(100, int(m.group(1)))) / 100.0
    cleaned = (text[:m.start()] + text[m.end():]).strip()
    return cleaned, val


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _append_event(db, run_id: str, seq: int, prev_hash: str, kind: str, data: dict) -> str:
    h = sha256_hex((prev_hash + sha256_hex(canonical(data))).encode())
    db.add(RunEvent(run_id=run_id, seq=seq, kind=kind, data=data, hash=h, prev_hash=prev_hash))
    return h


def execute_run(run_id: str, inline_key: str | None = None,
                inline_base_url: str | None = None) -> dict:
    db = session()
    try:
        run = db.get(WebRun, run_id)
        if not run:
            return {"ok": False, "error": "run not found"}
        run.status = "running"
        run.started_at = _now()
        run.progress = 0
        db.commit()

        # resolve key + base_url
        base_url = inline_base_url
        key = inline_key
        if run.credential_id:
            cred = db.get(ProviderCredential, run.credential_id)
            if not cred:
                return _fail(db, run, "credential no longer exists")
            key = security.decrypt_secret(cred.key_encrypted) if cred.key_encrypted else ""
            base_url = cred.base_url
        if key is None:
            return _fail(db, run, "no API key available for this run")

        try:
            conn = providers.connector(run.provider, key, run.model_name, base_url)
        except providers.ProviderError as e:
            return _fail(db, run, f"connector error: {e}")

        # generate a fresh, seeded pack (answers stay server-side)
        tasks = G.generate(family=run.family, n=run.n_tasks, seed=run.seed,
                           visibility="validation")
        keys = {t.task_id: schema.answer_key(t) for t in tasks}

        seq = 0
        prev = "0" * 64
        prev = _append_event(db, run.id, seq, prev, "run_start",
                             {"model": run.model_name, "provider": run.provider,
                              "n_tasks": len(tasks)})
        seq += 1
        db.commit()
        logger.info("run %s start: model=%s provider=%s base_url=%s n_tasks=%d",
                    run.id, run.model_name, run.provider, base_url or "(default)", len(tasks))

        responses = []
        consecutive_errors = 0
        last_error = None
        total_tokens = 0
        total_latency = 0.0
        successes = 0
        for i, t in enumerate(tasks):
            out, conf, latency_ms, err = "", None, 0.0, None
            t0 = time.perf_counter()
            # A transient network/5xx blip should not cost the model the whole task: retry
            # it a couple of times with a short backoff before recording an error. Auth
            # (401/403) and rate-limit (429) are NOT transient — surface them immediately
            # so the dedicated handlers below can abort or back off.
            for attempt in range(3):
                try:
                    raw = conn.complete(t.prompt + CONFIDENCE_INSTRUCTION)
                    out, conf = parse_confidence(raw)  # strip confidence from gradeable text
                    consecutive_errors = 0
                    successes += 1
                    err = None
                    break
                except Exception as e:  # noqa: BLE001 — provider/network error (detail kept)
                    err = f"{type(e).__name__}: {e}"
                    transient = not any(s in err for s in
                                        ("HTTP 401", "HTTP 403", "HTTP 429", "limit: 0"))
                    if transient and attempt < 2:
                        time.sleep(2 * (attempt + 1))
                        continue
                    last_error = err
                    consecutive_errors += 1
                    logger.warning("run %s task %s (model=%s) failed [%d in a row]: %s",
                                   run.id, t.task_id, run.model_name, consecutive_errors, err)
                    break
            latency_ms = (time.perf_counter() - t0) * 1000
            # Real per-task token usage from the provider; fall back to a len/4 estimate
            # for the completion count only when usage isn't reported. Errored tasks have
            # no usage.
            ptok, ctok, ttok = (None, None, None) if err else providers_usage_breakdown(conn)
            toks = ctok if ctok is not None else max(1, len(out) // 4)
            total_tokens += toks
            total_latency += latency_ms
            resp = {"id": t.task_id, "output": out, "latency_ms": latency_ms, "tokens": toks}
            if conf is not None:
                resp["confidence"] = conf
            if err:
                # Flag so central scoring excludes it instead of grading "" as incorrect.
                resp["error"] = err[:500]
            responses.append(resp)
            # Full per-task trace -> the repository. Pull the question/grader/expected from
            # the server-held answer key for this task.
            key = keys.get(t.task_id, {})
            grader = key.get("grader") or {}
            db.add(WebRunResponse(
                run_id=run.id, task_id=t.task_id, family=t.task_family,
                model_name=run.model_name, provider=run.provider,
                subdomain=t.subdomain, difficulty=t.difficulty, visibility=t.visibility,
                prompt=t.prompt + CONFIDENCE_INSTRUCTION,
                expected_answer_type=t.expected_answer_type,
                grader_type=grader.get("type"), grader_json=grader or None,
                expected_answer=(None if key.get("expected_answer") is None
                                 else str(key.get("expected_answer"))),
                canary=key.get("canary") or None,
                output=out, output_sha256=sha256_hex((out or "").encode()),
                confidence=conf, error=(err[:500] if err else None),
                latency_ms=round(latency_ms, 2),
                tokens=toks, prompt_tokens=ptok, completion_tokens=ctok, total_tokens=ttok))
            ev = {"id": t.task_id, "ok": err is None,
                  "output_sha256": sha256_hex((out or "").encode())}
            if err:
                ev["error"] = err[:500]
            prev = _append_event(db, run.id, seq, prev, "task_response", ev)
            seq += 1
            run.progress = int(100 * (i + 1) / len(tasks))
            if i % 5 == 0 or i == len(tasks) - 1:
                db.commit()
            # abort early if the provider is rejecting us (bad key / model / quota)
            if last_error:
                _e = last_error
                if "HTTP 429" in _e:
                    # Hard quota exhaustion (limit: 0) — retrying never helps
                    if "limit: 0" in _e or "limit:0" in _e:
                        msg = (
                            "Provider quota exhausted for this model (quota limit is 0). "
                            "This model may not be available on your current plan, or it was "
                            "just launched and quotas are still being provisioned. "
                            "Try gemini-2.5-flash or gemini-2.0-flash instead."
                        )
                        logger.error("run %s aborted (hard quota): %s", run.id, _e[:400])
                        return _fail(db, run, msg)
                    # Soft rate-limit (RPM exceeded) — back off and let the outer retry loop handle it
                    if consecutive_errors == 1:
                        logger.warning("run %s rate-limited (429), backing off 60 s", run.id)
                        time.sleep(60)
                    elif consecutive_errors == 2:
                        logger.warning("run %s rate-limited again (429), backing off 120 s", run.id)
                        time.sleep(120)
                    # After 3 consecutive rate-limit 429s, give up
                    elif consecutive_errors >= 3:
                        msg = "Provider rate-limit (HTTP 429) hit 3 times in a row — reduce the number of tasks or try again later."
                        logger.error("run %s aborted (rate limit): %s", run.id, _e[:300])
                        return _fail(db, run, msg)
                # 401/403 — bad or expired key; retrying won't help
                elif "HTTP 401" in _e or "HTTP 403" in _e:
                    msg = "Provider rejected the API key (HTTP 401/403) — check that the key is valid and has not expired."
                    logger.error("run %s aborted (auth): %s", run.id, _e[:300])
                    return _fail(db, run, msg)
            if consecutive_errors >= 5:
                msg = f"provider call failed {consecutive_errors}× in a row — last error: {last_error}"
                logger.error("run %s aborted: %s", run.id, msg)
                return _fail(db, run, msg)

        # If the provider answered nothing, there is no model behaviour to score — fail
        # the run with the last error rather than emitting a meaningless all-excluded 0.
        if successes == 0:
            return _fail(db, run, f"provider answered 0/{len(tasks)} tasks — "
                                  f"last error: {last_error or 'unknown'}")

        # --- central re-scoring + signed report ---
        er = evaluate.score_pack(keys, responses)
        # Sign with the server's STABLE identity (not a throwaway key) so the report's
        # verification appendix actually verifies against the published public key.
        signer = security.report_signer()
        rep = report_mod.build_report(
            run.model_name, f"Xodexa Live ({run.provider})", er,
            telemetry={"tokens": total_tokens, "latency_ms": round(total_latency),
                       "avg_latency_ms": round(total_latency / max(1, len(responses)), 1)},
            signer=signer)
        rep["family_scores"] = er["family_scores"]  # for the live leaderboard/compare pages

        # Persist the per-item score aggregate AND backfill it onto the repository trace
        # rows so each trace carries its central score/verdict in one place.
        trace_by_task = {r.task_id: r for r in db.query(WebRunResponse)
                         .filter(WebRunResponse.run_id == run.id).all()}
        for it in er["per_item"]:
            db.add(WebRunItemScore(run_id=run.id, task_id=it["task_id"], family=it["family"],
                                   category=it["category"], awarded=it["awarded"],
                                   max_points=it["max"], verdict=it["verdict"],
                                   difficulty=it.get("difficulty")))
            tr = trace_by_task.get(it["task_id"])
            if tr is not None:
                tr.category = it["category"]
                tr.awarded = it["awarded"]
                tr.max_points = it["max"]
                tr.verdict = it["verdict"]
        ar = rep["agi_readiness"]
        db.add(Report(run_id=run.id, user_id=run.user_id, report_json=rep,
                      xodexa_score=rep["xodexa_score"], grade=rep["grade"],
                      agi_index=ar["agi_readiness_index"], agi_level=ar["level"],
                      body_sha256=rep["verification_appendix"]["body_sha256"],
                      signer_pub=rep["verification_appendix"]["signer_pub"],
                      signature=rep["verification_appendix"]["signature"]))

        run.xodexa_score = rep["xodexa_score"]
        run.grade = rep["grade"]
        run.agi_index = ar["agi_readiness_index"]
        run.agi_level = ar["level"]
        run.accuracy = rep["frontier_metrics"]["accuracy"]
        run.calibration_error = rep["frontier_metrics"]["calibration_error"]
        run.tokens = total_tokens
        run.latency_ms = round(total_latency, 1)
        run.progress = 100
        run.status = "scored"
        run.finished_at = _now()
        _append_event(db, run.id, seq, prev, "run_scored",
                      {"xodexa_score": run.xodexa_score, "agi_level": run.agi_level})
        db.commit()
        logger.info("run %s scored: xodexa_score=%s grade=%s agi_level=%s",
                    run.id, run.xodexa_score, run.grade, run.agi_level)
        return {"ok": True, "run_id": run.id, "xodexa_score": run.xodexa_score}
    except Exception as e:  # noqa: BLE001 — never leave a run stuck; record the reason
        logger.exception("run %s crashed", run_id)
        try:
            db.rollback()
            run = db.get(WebRun, run_id)
            if run and run.status not in ("scored", "failed"):
                run.status = "failed"
                run.error = f"internal error: {type(e).__name__}: {e}"
                run.finished_at = _now()
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("run %s: failed to record failure", run_id)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()


def _fail(db, run: WebRun, message: str) -> dict:
    run.status = "failed"
    run.error = message
    run.finished_at = _now()
    db.commit()
    return {"ok": False, "error": message}
