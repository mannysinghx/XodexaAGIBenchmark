-- Xodexa AGI Benchmark — PostgreSQL schema (Phase 1).
-- Backs the xodexa ScoringAuthority in production. Organized by concern.
-- Conventions: UUID PKs, created_at on everything, append-only tables noted.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ===================== Identity & tenancy =====================
CREATE TABLE organizations (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    slug         TEXT UNIQUE NOT NULL,
    plan         TEXT NOT NULL DEFAULT 'community',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID REFERENCES organizations(id) ON DELETE CASCADE,
    email        TEXT UNIQUE NOT NULL,
    display_name TEXT,
    idp_subject  TEXT,                          -- Ory/Keycloak subject
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE roles (
    id    SERIAL PRIMARY KEY,
    name  TEXT UNIQUE NOT NULL                  -- owner|admin|maintainer|member|viewer
);

CREATE TABLE user_roles (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    org_id  UUID REFERENCES organizations(id) ON DELETE CASCADE,
    role_id INT  REFERENCES roles(id),
    PRIMARY KEY (user_id, org_id, role_id)
);

CREATE TABLE api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT,
    hashed_key  TEXT NOT NULL,                  -- never store plaintext
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    last_used_at TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===================== Runners (self-hosted) =====================
CREATE TABLE runners (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID REFERENCES organizations(id) ON DELETE CASCADE,
    label         TEXT,
    version       TEXT NOT NULL,
    fingerprint   TEXT UNIQUE NOT NULL,
    verified      BOOLEAN NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE runner_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runner_id   UUID REFERENCES runners(id) ON DELETE CASCADE,
    public_key  TEXT NOT NULL,                  -- base64 Ed25519
    active      BOOLEAN NOT NULL DEFAULT true,
    rotated_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE runner_attestations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    runner_id   UUID REFERENCES runners(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                  -- none|sev-snp|tdx|nitro|gcp-cvm|azure-cc
    evidence    JSONB,
    verified    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===================== Models =====================
CREATE TABLE model_providers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,                  -- openai|anthropic|google|mistral|xai|local|...
    kind        TEXT NOT NULL                   -- api|open-source|local
);

CREATE TABLE models (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID REFERENCES organizations(id) ON DELETE SET NULL,
    provider_id   UUID REFERENCES model_providers(id),
    name          TEXT NOT NULL,
    family        TEXT,
    params_b      NUMERIC,
    is_open_source BOOLEAN NOT NULL DEFAULT false,
    context_length INT,
    metadata      JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_endpoints (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id    UUID REFERENCES models(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                  -- openai|ollama|vllm|tgi|llamacpp|custom
    base_url    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===================== Benchmarks =====================
CREATE TABLE benchmark_suites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pack_id     TEXT UNIQUE NOT NULL,           -- e.g. xodexa-omega
    name        TEXT NOT NULL,
    engine      TEXT NOT NULL,                  -- xodexa-omega|lm-eval|inspect|helm|...
    categories  TEXT[] NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE benchmark_versions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suite_id     UUID REFERENCES benchmark_suites(id) ON DELETE CASCADE,
    version      TEXT NOT NULL,
    layer        SMALLINT NOT NULL,             -- 1 public | 2 generated | 3 private-hidden
    is_active     BOOLEAN NOT NULL DEFAULT true,
    rotated_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (suite_id, version)
);

CREATE TABLE benchmark_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      UUID REFERENCES benchmark_versions(id) ON DELETE CASCADE,
    task_key        TEXT NOT NULL,              -- stable id, e.g. AR-01
    category        TEXT NOT NULL,
    visibility      TEXT NOT NULL,              -- public|private|hidden|generated-per-run
    difficulty      NUMERIC,                    -- EMPIRICAL (IRT), not hand-set
    scoring_rubric  JSONB NOT NULL,
    -- answer keys / hidden tests are NEVER exposed via API; stored encrypted at rest
    answer_key_enc  BYTEA,
    provenance      JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE benchmark_task_variants (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id     UUID REFERENCES benchmark_tasks(id) ON DELETE CASCADE,
    run_id      UUID,                           -- generated per run from nonce seed
    seed_hash   TEXT NOT NULL,
    canary      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE task_manifests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL,
    manifest      JSONB NOT NULL,
    manifest_hash TEXT NOT NULL,
    signature     TEXT NOT NULL,                -- server Ed25519 signature
    nonce         TEXT UNIQUE NOT NULL,         -- replay protection
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===================== Runs & results =====================
CREATE TABLE benchmark_runs (
    id              UUID PRIMARY KEY,           -- immutable run_id
    org_id          UUID REFERENCES organizations(id) ON DELETE SET NULL,
    runner_id       UUID REFERENCES runners(id),
    model_id        UUID REFERENCES models(id),
    suite_id        UUID REFERENCES benchmark_suites(id),
    benchmark_version TEXT NOT NULL,
    mode            TEXT NOT NULL,              -- official|comparison
    status          TEXT NOT NULL DEFAULT 'issued', -- issued|submitted|verified|flagged|rejected
    attestation     TEXT NOT NULL DEFAULT 'none',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- append-only
CREATE TABLE run_events (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    seq         INT NOT NULL,
    kind        TEXT NOT NULL,
    data        JSONB NOT NULL,
    hash        TEXT NOT NULL,                  -- hash-chain link
    prev_hash   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, seq)
);

CREATE TABLE result_bundles (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    manifest_hash TEXT NOT NULL,
    event_log_hash TEXT NOT NULL,
    runner_signature TEXT NOT NULL,
    environment   JSONB NOT NULL,
    token_usage   JSONB,
    latency       JSONB,
    bundle_enc    BYTEA,                        -- encrypted full bundle at rest
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE model_responses (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    task_key    TEXT NOT NULL,
    output      TEXT,
    output_sha256 TEXT,
    latency_ms  NUMERIC,
    tokens      INT
);

CREATE TABLE evaluator_results (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    task_key    TEXT NOT NULL,
    category    TEXT NOT NULL,
    awarded     NUMERIC NOT NULL,
    max_points  NUMERIC NOT NULL,
    verdict     TEXT
);

CREATE TABLE hidden_test_results (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    task_key    TEXT NOT NULL,
    passed      INT, total INT, detail JSONB
);

CREATE TABLE judge_results (
    id          BIGSERIAL PRIMARY KEY,
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    task_key    TEXT NOT NULL,
    judge_kind  TEXT NOT NULL,                  -- llm|human|rubric
    score       NUMERIC, rationale TEXT
);

-- ===================== Scoring & leaderboard =====================
CREATE TABLE leaderboard_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID REFERENCES benchmark_runs(id),
    model_id            UUID REFERENCES models(id),
    apex_score          NUMERIC NOT NULL,
    ci_low              NUMERIC, ci_high NUMERIC,
    grade               TEXT NOT NULL,
    coverage            NUMERIC NOT NULL,
    verification_status TEXT NOT NULL,          -- Verified, non-attested | Verified + Attested | ...
    attestation         TEXT NOT NULL,
    category_breakdown  JSONB NOT NULL,
    official_signature  TEXT NOT NULL,          -- server signature over the official record
    published_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE human_baselines (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    suite_id    UUID REFERENCES benchmark_suites(id),
    category    TEXT NOT NULL,
    human_score NUMERIC, expert_score NUMERIC
);

-- ===================== Integrity & analysis =====================
CREATE TABLE failure_reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    task_key    TEXT NOT NULL,
    category    TEXT, difficulty NUMERIC,
    failure_type TEXT NOT NULL,                 -- hallucination|bad_reasoning|tool_misuse|...
    severity    TEXT, reproducible BOOLEAN,
    expected    TEXT, actual TEXT, evidence JSONB,
    suggestion  TEXT
);

CREATE TABLE contamination_checks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                  -- canary|perfect_score|timing|pattern
    signal      NUMERIC NOT NULL, detail JSONB
);

CREATE TABLE canary_checks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    task_key    TEXT NOT NULL, canary TEXT NOT NULL, leaked BOOLEAN NOT NULL
);

-- ===================== Plugins =====================
CREATE TABLE plugin_registry (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL,                  -- benchmark_pack|adapter|scorer|tool_env|...
    author      TEXT, license TEXT,
    approved    BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE plugin_versions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_id   UUID REFERENCES plugin_registry(id) ON DELETE CASCADE,
    version     TEXT NOT NULL,
    manifest    JSONB NOT NULL,
    sbom        JSONB,
    checksum    TEXT NOT NULL,
    permissions JSONB NOT NULL,
    sandbox_policy JSONB NOT NULL,
    UNIQUE (plugin_id, version)
);

CREATE TABLE plugin_signatures (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plugin_version_id UUID REFERENCES plugin_versions(id) ON DELETE CASCADE,
    signer      TEXT NOT NULL, signature TEXT NOT NULL, cosign_bundle JSONB
);

-- ===================== Audit & security (append-only) =====================
CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    org_id      UUID, actor TEXT, action TEXT NOT NULL,
    target      TEXT, data JSONB, hash TEXT, prev_hash TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE security_events (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT NOT NULL,                  -- forged_manifest|tamper|canary_leak|replay|...
    severity    TEXT NOT NULL, run_id UUID, detail JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE exported_reports (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID REFERENCES benchmark_runs(id) ON DELETE CASCADE,
    format      TEXT NOT NULL,                  -- pdf|markdown|json|csv|openai-evals|helm|inspect|lm-eval
    location    TEXT NOT NULL,                  -- MinIO/S3 object key
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===================== Helpful indexes =====================
CREATE INDEX idx_runs_model       ON benchmark_runs(model_id);
CREATE INDEX idx_runs_status      ON benchmark_runs(status);
CREATE INDEX idx_lb_score         ON leaderboard_entries(apex_score DESC);
CREATE INDEX idx_events_run       ON run_events(run_id, seq);
CREATE INDEX idx_responses_run    ON model_responses(run_id);
CREATE INDEX idx_sec_kind         ON security_events(kind);
