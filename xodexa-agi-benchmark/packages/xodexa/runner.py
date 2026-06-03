"""
xodexa.runner
===============
The self-hosted execution agent — the open-source half of the platform. It runs on
the MODEL PROVIDER's infrastructure and is *structurally incapable* of producing an
official score (ANALYSIS.md §6): it has no answer keys in official mode, no leaderboard
credential, and no scoring authority.

What it does:
  * Proves possession of its private key during registration.
  * Pulls a server-signed manifest + prompts-only task bundle, verifies the server
    signature before executing anything.
  * Runs INFERENCE only, via a pluggable model connector.
  * Records a hash-chained, tamper-evident event log.
  * Signs the result bundle (raw outputs + traces + metadata) and submits it.
  * In 'comparison' mode only (graders shipped), computes an advisory LOCAL score that
    is always labelled "not official".
"""

from __future__ import annotations

import time

from .crypto import KeyPair, HashChain, sha256_hex, verify

RUNNER_VERSION = "0.1.0"


# --------------------------------------------------------------------------- #
# Model connectors  (provider runs inference locally; weights never leave)
# --------------------------------------------------------------------------- #

class ModelConnector:
    """Base connector. Implement `complete(prompt) -> str`."""
    name = "base"

    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class CallableConnector(ModelConnector):
    """Wrap any python callable as a model (used in tests/demos)."""
    def __init__(self, fn, name="callable"):
        self.fn = fn
        self.name = name

    def complete(self, prompt: str) -> str:
        return self.fn(prompt)


class OpenAICompatibleConnector(ModelConnector):
    """
    Works against ANY OpenAI-compatible /v1/chat/completions endpoint: vLLM, TGI,
    Ollama (/v1), LM Studio, OpenRouter, llama.cpp server, or the OpenAI API itself.
    """
    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, api_key: str = "not-needed",
                 timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def complete(self, prompt: str) -> str:
        import json
        import urllib.request
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
        }).encode()
        req = urllib.request.Request(
            self.base_url + "/chat/completions", data=body,
            headers={"Authorization": "Bearer " + self.api_key,
                     "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.load(r)
        return data["choices"][0]["message"]["content"]


class OllamaConnector(ModelConnector):
    """Native Ollama /api/generate endpoint (no OpenAI shim required)."""
    name = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def complete(self, prompt: str) -> str:
        import json
        import urllib.request
        body = json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode()
        req = urllib.request.Request(self.base_url + "/api/generate", data=body,
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r).get("response", "")


# --------------------------------------------------------------------------- #
# Runner agent
# --------------------------------------------------------------------------- #

class RunnerAgent:
    def __init__(self, key: KeyPair | None = None):
        self.key = key or KeyPair.generate()
        self.runner_id: str | None = None
        self.server_pub: str | None = None

    # registration ------------------------------------------------------------
    def register(self, authority) -> str:
        reg = authority.register_runner(self.key.pub_b64, RUNNER_VERSION)
        self.runner_id = reg["runner_id"]
        self.server_pub = reg["server_pub"]
        signed = self.key.sign({"challenge": reg["challenge"]})
        if not authority.confirm_runner(self.runner_id, signed):
            raise RuntimeError("runner key challenge failed")
        return self.runner_id

    # execution ---------------------------------------------------------------
    def execute(self, issued: dict, connector: ModelConnector,
                model_id: str, attestation: str = "none") -> dict:
        manifest = issued["manifest"]
        # Verify the SERVER signed this manifest before doing anything.
        if not verify(self.server_pub, manifest, issued["signature"]):
            raise RuntimeError("server manifest signature invalid — refusing to run")

        log = HashChain()
        log.append("run_start", {"run_id": manifest["run_id"], "model_id": model_id,
                                 "runner_version": RUNNER_VERSION})

        responses, tokens_total = [], 0
        for task in issued["public_tasks"]:
            t0 = time.perf_counter()
            raw = connector.complete(task["prompt"])
            latency_ms = (time.perf_counter() - t0) * 1000
            # A connector may return a plain string, or (text, confidence), or a dict
            # {"text":..., "confidence":...} to support HLE-style calibration metrics.
            confidence = None
            if isinstance(raw, tuple):
                output, confidence = raw
            elif isinstance(raw, dict):
                output, confidence = raw.get("text", ""), raw.get("confidence")
            else:
                output = raw
            approx_tokens = max(1, len(output) // 4)
            tokens_total += approx_tokens
            resp = {"id": task["id"], "output": output,
                    "latency_ms": round(latency_ms, 2), "tokens": approx_tokens}
            if confidence is not None:
                resp["confidence"] = float(confidence)
            responses.append(resp)
            log.append("task_response", {"id": task["id"],
                                         "output_sha256": sha256_hex((output or "").encode()),
                                         "latency_ms": round(latency_ms, 2)})

        log.append("run_end", {"tasks": len(responses), "tokens": tokens_total})

        core = {
            "run_id": manifest["run_id"],
            "runner_id": self.runner_id,
            "model_id": model_id,
            "pack_id": manifest["pack_id"],
            "benchmark_version": manifest["benchmark_version"],
            "manifest_hash": sha256_hex(manifest),
            "mode": manifest["mode"],
            "started_at": log.entries[0]["event"]["ts"],
            "completed_at": time.time(),
            "environment": {
                "runner_version": RUNNER_VERSION,
                "docker_image_digest": "sha256:demo-no-image",
                "hardware_summary": "demo-cpu",
                "attestation": attestation,
            },
            "responses": responses,
            "token_usage": {"total": tokens_total},
            "latency": {"total_ms": round(sum(r["latency_ms"] for r in responses), 2)},
            "event_log": {"entries": log.export(), "head": log.head()},
        }

        # advisory LOCAL score, only when graders were shipped (comparison mode)
        if manifest["mode"] == "comparison" and all("grader" in t for t in issued["public_tasks"]):
            core["local_score"] = self._local_score(issued["public_tasks"], responses)

        signature = self.key.sign(core)
        return {**core, "signature": signature}

    # advisory local scoring (NEVER official) ---------------------------------
    @staticmethod
    def _local_score(public_tasks, responses):
        import importlib.util
        import sys
        from pathlib import Path
        xodex = Path(__file__).resolve().parents[3] / "xodex_omega" / "harness.py"
        spec = importlib.util.spec_from_file_location("xodex_harness_local", xodex)
        h = importlib.util.module_from_spec(spec)
        sys.modules["xodex_harness_local"] = h
        spec.loader.exec_module(h)
        by_id = {r["id"]: r["output"] for r in responses}
        aw = mx = 0.0
        for t in public_tasks:
            item = {"grader": t["grader"], "points": t.get("points", 1),
                    "negative": t.get("negative", 0)}
            a, m, _ = h.grade(item, by_id.get(t["id"], ""))
            aw += a
            mx += m
        return {"label": "Local score — NOT official",
                "raw": round(aw, 2), "max": mx,
                "pct": round(max(0.0, aw) / mx * 100, 2) if mx else 0.0}
