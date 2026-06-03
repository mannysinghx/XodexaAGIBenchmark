# The xodexa-runner

`xodexa-runner` is the open-source, self-hosted half of the platform. It runs on the model
provider's infrastructure, runs **inference only**, and is **structurally incapable** of
issuing an official score (see [SECURITY_MODEL.md](./SECURITY_MODEL.md)). It is implemented
in `packages/xodexa/runner.py` and driven by the CLI in `apps/runner-cli/xodexa.py`.

---

## 1. Model connectors

The provider runs inference locally; weights never leave their infrastructure. Connectors
subclass `runner.ModelConnector` and implement `complete(prompt) -> str`.

| Connector | Targets | Endpoint |
|---|---|---|
| `CallableConnector(fn, name=...)` | Any Python callable (tests/demos). | in-process |
| `OpenAICompatibleConnector(base_url, model, api_key="not-needed", timeout=120.0)` | **vLLM, TGI, Ollama (`/v1`), LM Studio, llama.cpp server, OpenRouter, the OpenAI API itself** | `POST {base_url}/chat/completions` |
| `OllamaConnector(base_url="http://localhost:11434", model="llama3")` | Native Ollama (no OpenAI shim) | `POST {base_url}/api/generate` |

A connector may return a plain string, a `(text, confidence)` tuple, or a
`{"text": ..., "confidence": ...}` dict — confidence, when present, feeds the HLE-style
calibration metrics.

```python
from xodexa import OpenAICompatibleConnector, OllamaConnector, CallableConnector

vllm   = OpenAICompatibleConnector("http://localhost:8000/v1", "my-model")
ollama = OllamaConnector("http://localhost:11434", "llama3")
demo   = CallableConnector(lambda prompt: "42", name="callable:demo")
```

---

## 2. The official scoring flow

```
register → key challenge → signed manifest → inference
        → signed result bundle → submit → central re-score → verified score
```

1. **register** — `RunnerAgent.register(authority)` sends the runner's public key +
   version; the authority returns a `runner_id`, a `challenge`, and the `server_pub`.
2. **key challenge** — the runner signs the challenge with its private key; the authority
   verifies possession (`confirm_runner`). Unverified runners cannot get a manifest.
3. **signed manifest** — `authority.issue_manifest(runner_id, pack_id, mode="official")`
   returns a server-signed manifest (fresh nonce, per-run seed, `task_ids`) plus
   **public-view tasks only** (`scoring: "central-only"` — graders/answers withheld). The
   runner **verifies the server signature before executing** (`runner.execute` refuses an
   invalid signature).
4. **inference** — the runner runs the connector over each prompt, recording latency and an
   approximate token count, and appends every response to a **hash-chained event log**.
5. **signed result bundle** — the runner signs the bundle (raw outputs + traces + the
   manifest hash + the event log + head) with its private key.
6. **submit + central re-score** — `authority.verify_and_score(bundle)` runs the hard
   integrity gates (signature, manifest binding, nonce freshness, chain integrity, version),
   **re-scores from raw outputs against server-held keys**, runs the contamination/anomaly
   checks, computes the Xodexa Score + frontier metrics, and assigns a status.
7. **verified score** — a clean run becomes **Verified, non-attested** (or **Verified +
   Attested** if an environment attestation is present); flags move it to **flagged**;
   integrity-gate failures are **rejected**. The authority signs the official record.

### Local vs official scoring

In `comparison` mode the manifest **ships graders**, so the runner can compute an advisory
`local_score`, always labelled `"Local score — NOT official"`. In `official` mode no
graders are shipped and the runner cannot self-score. **Only the central authority issues an
official score** — never the runner.

---

## 3. CLI commands

`apps/runner-cli/xodexa.py` exposes these commands (the ones that are wired):

```bash
xodexa benchmark list                 # list available benchmark packs
xodexa run    --model <connector> [--suite <pack>] [--mode official|comparison]
              [--attestation <s>] [--local]
xodexa verify <bundle.json>           # check the event-log hash chain locally
xodexa export --run <report.json> --format json|markdown
xodexa status                         # runner version, mode, connectors
```

Global flag `--server <URL>` points at a live main app; otherwise use `--local` for a
self-contained in-process authority (handy for development and for proving the runner
cannot self-issue official scores).

`run` flags: `--model` (required), `--suite` (default `xodexa-omega`), `--mode`
(`official` | `comparison`, default `official`), `--attestation` (default `none`),
`--local`.

### `--model` connector specs

| Spec | Meaning |
|---|---|
| `callable:good` | built-in simulated competent model (local demo only) |
| `callable:bluffer` | built-in simulated hallucinating model (local demo only) |
| `openai:<base_url>#<model>` | any OpenAI-compatible endpoint (vLLM/TGI/Ollama/LM Studio/…) |
| `ollama:<base_url>#<model>` | native Ollama endpoint |

### Examples

```bash
# local demo flow (no server), official + comparison
python apps/runner-cli/xodexa.py benchmark list
python apps/runner-cli/xodexa.py run --model callable:good     --mode official   --local
python apps/runner-cli/xodexa.py run --model callable:bluffer  --mode comparison --local

# point at a real endpoint
python apps/runner-cli/xodexa.py run --model "openai:http://localhost:8000/v1#my-model" --local
python apps/runner-cli/xodexa.py run --model "ollama:http://localhost:11434#llama3"     --local

# verify a saved bundle's hash chain, and export a report
python apps/runner-cli/xodexa.py verify results/<run>.bundle.json
python apps/runner-cli/xodexa.py export --run results/<run>.report.json --format markdown
```

`run` writes `results/<run_id>.bundle.json` and `results/<run_id>.report.json`. Note that
`xodexa verify` only checks the **event-log hash chain locally** — full signature,
manifest, and nonce verification is performed **server-side by the main app**, exactly as
the trust boundary requires.
