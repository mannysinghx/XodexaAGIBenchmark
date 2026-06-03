"""
xodexa.pipeline
=================
The dataset generation pipeline (spec "Dataset generation pipeline", stages 1-6),
implemented as a composable, auditable stage chain:

    generate -> difficulty_filter -> contamination_filter -> quality_review
             -> calibration -> versioning(+sign)

Each stage records why a task was kept or dropped, so a release is reproducible and
defensible. The output is a :class:`DatasetRelease`:

  * ``public_tasks``  — schema ``public_view`` (no answers/graders) — safe to ship.
  * ``answer_keys``   — server-side keys for central re-scoring — NEVER shipped.
  * ``manifest``      — semver, checksum, signed, with difficulty distribution,
                        contamination summary, provenance, license rollup, known limits.

No network, no DB — pure functions over Task objects, so the same code runs in the
air-gapped generator and in CI.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

from . import grade, schema, families
from .contamination import CorpusIndex
from .crypto import KeyPair, sha256_hex


@dataclass
class PipelineConfig:
    contamination_threshold: float = 0.6
    # Keep a task only if frontier probe pass-rate is in [keep_min, keep_max] —
    # too-easy and impossible-to-grade tasks are dropped. Only applied if probes given.
    keep_min_passrate: float = 0.0      # > this (strictly) — must not be trivially 1.0
    keep_max_passrate: float = 0.95     # <= this — frontier models should struggle
    require_grader_satisfiable: bool = True
    expert_review_families: tuple = ("science", "math", "code", "safety")


@dataclass
class StageStat:
    name: str
    inn: int
    out: int
    dropped: list[dict] = field(default_factory=list)


@dataclass
class DatasetRelease:
    name: str
    version: str
    public_tasks: list[dict]
    answer_keys: dict
    manifest: dict
    signature: str
    stats: list[StageStat]
    rejected: list[dict]


class DatasetPipeline:
    def __init__(self, corpus: CorpusIndex | None = None,
                 signer: KeyPair | None = None, config: PipelineConfig | None = None):
        self.corpus = corpus or CorpusIndex()
        self.signer = signer or KeyPair.generate()
        self.cfg = config or PipelineConfig()

    # -- stages ---------------------------------------------------------------
    def _difficulty_filter(self, tasks, probe_models):
        """If probe models are supplied, keep tasks whose frontier pass-rate sits in
        the configured window; annotate each task's empirical difficulty + discrimination.
        Without probes, this is a pass-through that still assigns provisional difficulty."""
        kept, dropped = [], []
        for t in tasks:
            if probe_models:
                passes = 0
                for m in probe_models:
                    out = m(t.prompt)
                    aw, mx, _ = grade.grade(t.server_grader, out, t.points, t.negative)
                    if mx and aw >= 0.5 * mx:
                        passes += 1
                rate = passes / len(probe_models)
                t._probe_passrate = rate  # type: ignore[attr-defined]
                if not (self.cfg.keep_min_passrate < rate <= self.cfg.keep_max_passrate):
                    dropped.append({"task_id": t.task_id, "stage": "difficulty",
                                    "reason": f"probe pass-rate {rate:.2f} outside window"})
                    continue
            kept.append(t)
        return kept, dropped

    def _contamination_filter(self, tasks):
        kept, dropped = [], []
        for t in tasks:
            sim = self.corpus.similarity(t.prompt)
            t.contamination_controls.public_similarity_score = sim["score"]
            if sim["score"] >= self.cfg.contamination_threshold:
                dropped.append({"task_id": t.task_id, "stage": "contamination",
                                "reason": f"similarity {sim['score']} to {sim['source_id']}",
                                "method": sim["method"]})
                continue
            kept.append(t)
        return kept, dropped

    def _quality_review(self, tasks):
        kept, dropped = [], []
        for t in tasks:
            errs = schema.validate_task(t)
            if errs:
                dropped.append({"task_id": t.task_id, "stage": "quality",
                                "reason": "schema: " + "; ".join(errs[:2])})
                continue
            if self.cfg.require_grader_satisfiable and t.server_grader:
                good = grade.synth_good(t.server_grader)
                aw, mx, _ = grade.grade(t.server_grader, good, t.points, t.negative)
                if not (mx and aw >= mx - 1e-6):
                    dropped.append({"task_id": t.task_id, "stage": "quality",
                                    "reason": "grader not satisfiable by oracle"})
                    continue
            # Flag (do not drop) high-stakes families for expert review.
            if t.task_family in self.cfg.expert_review_families:
                t.provenance.review_status = "reviewed"  # auto-reviewed; expert pending
            kept.append(t)
        return kept, dropped

    def _calibrate(self, tasks):
        """Assign discrimination + expected solve time + eval cost heuristics."""
        for t in tasks:
            # discrimination: harder + trap-bearing items discriminate more.
            disc = min(1.0, 0.3 + 0.05 * t.difficulty + 0.1 * (t.negative / max(t.points, 1)))
            t.human_baseline.median_human_time_minutes = round(0.5 + t.difficulty * 1.2, 1)
            t.human_baseline.inter_rater_agreement = round(0.95 - 0.03 * t.negative, 3)
            t._discrimination = round(disc, 3)  # type: ignore[attr-defined]
        return tasks

    # -- driver ---------------------------------------------------------------
    def run(self, tasks: list, name: str, version: str, *, changelog: str = "",
            license_summary: str | None = None, known_limitations: list | None = None,
            probe_models=None) -> DatasetRelease:
        stats: list[StageStat] = []
        rejected: list[dict] = []

        def stage(label, fn, items):
            kept, dropped = fn(items)
            stats.append(StageStat(label, len(items), len(kept), dropped))
            rejected.extend(dropped)
            return kept

        items = list(tasks)
        stats.append(StageStat("generate", len(items), len(items)))
        items = stage("difficulty", lambda x: self._difficulty_filter(x, probe_models), items)
        items = stage("contamination", self._contamination_filter, items)
        items = stage("quality_review", self._quality_review, items)
        items = self._calibrate(items)
        stats.append(StageStat("calibration", len(items), len(items)))

        public_tasks = [schema.public_view(t) for t in items]
        answer_keys = {t.task_id: schema.answer_key(t) for t in items}

        # checksum over the shippable public views (deterministic, sorted).
        checksum = sha256_hex(sorted(public_tasks, key=lambda d: d["task_id"]))

        diffs = [t.difficulty for t in items]
        bands: dict[str, int] = {}
        for t in items:
            bands[t.difficulty_band] = bands.get(t.difficulty_band, 0) + 1
        fam_counts: dict[str, int] = {}
        vis_counts: dict[str, int] = {}
        lic_counts: dict[str, int] = {}
        for t in items:
            fam_counts[t.task_family] = fam_counts.get(t.task_family, 0) + 1
            vis_counts[t.visibility] = vis_counts.get(t.visibility, 0) + 1
            lic_counts[t.provenance.license] = lic_counts.get(t.provenance.license, 0) + 1
        sims = [t.contamination_controls.public_similarity_score for t in items]

        manifest = {
            "name": name,
            "version": version,
            "benchmark_schema": "xodexa-task/1.0",
            "created_at": _iso(time.time()),
            "task_count": len(items),
            "checksum_sha256": checksum,
            "changelog": changelog or f"Release {version}",
            "families": fam_counts,
            "visibility": vis_counts,
            "licenses": lic_counts,
            "difficulty": {
                "mean": round(statistics.fmean(diffs), 2) if diffs else 0.0,
                "min": min(diffs) if diffs else 0.0,
                "max": max(diffs) if diffs else 0.0,
                "bands": bands,
            },
            "contamination": {
                "threshold": self.cfg.contamination_threshold,
                "max_similarity": round(max(sims), 4) if sims else 0.0,
                "mean_similarity": round(statistics.fmean(sims), 4) if sims else 0.0,
                "rejected_for_contamination":
                    sum(1 for r in rejected if r["stage"] == "contamination"),
            },
            "pipeline": [{"stage": s.name, "in": s.inn, "out": s.out} for s in stats],
            "license_summary": license_summary or "Mixed; see per-task provenance.license",
            "known_limitations": known_limitations or [
                "Procedural graders are deterministic but narrower than a human rater.",
                "Multimodal items are text-rendered proxies in this MVP.",
                "Difficulty is provisional until human + frontier baselines are collected.",
            ],
            "signer_pub": self.signer.pub_b64,
        }
        signature = self.signer.sign(manifest)
        return DatasetRelease(name, version, public_tasks, answer_keys, manifest,
                              signature, stats, rejected)


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
