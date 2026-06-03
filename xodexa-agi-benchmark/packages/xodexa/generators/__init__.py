"""
xodexa.generators
===================
Procedural task generators — the engine behind Layer 3 (dynamic, runtime-generated
tasks) and the Layer 1/2 seed corpora. Each generator is a small deterministic
function ``gen(rng, idx, visibility) -> Task`` keyed by a stable ``generator_id``
(``<family>.<subdomain>``). A seed makes any corpus reproducible; changing the seed
yields a fresh, memorization-resistant variant.

The registry is the catalogue the platform exposes as "N dynamic task generators".
Add a generator by decorating it with ``@register("family.subdomain", family=...)``.

Security: generators mint a per-task canary and build a server-side ``server_grader``.
``schema.new_task`` strips the answer from any hidden/dynamic task automatically;
``schema.public_view`` strips the grader before anything ships to a runner.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from .. import families
from ..crypto import sha256_hex
from ..schema import Task

GenFn = Callable[[random.Random, int, str], Task]


@dataclass
class GeneratorSpec:
    generator_id: str
    family: str
    fn: GenFn
    blurb: str


REGISTRY: dict[str, GeneratorSpec] = {}


def register(generator_id: str, family: str, blurb: str = ""):
    def deco(fn: GenFn) -> GenFn:
        if generator_id in REGISTRY:
            raise ValueError(f"duplicate generator id: {generator_id}")
        REGISTRY[generator_id] = GeneratorSpec(generator_id, family, fn, blurb or fn.__doc__ or "")
        return fn
    return deco


# -- shared helpers used by every family module -------------------------------

def canary(seed: int, generator_id: str, idx: int) -> str:
    h = sha256_hex(f"{seed}:{generator_id}:{idx}:xodexa-canary".encode())[:12]
    return f"XDX-CANARY-{h}"


def task_id(generator_id: str, seed: int, idx: int) -> str:
    h = sha256_hex(f"{generator_id}:{seed}:{idx}".encode())[:10]
    return f"xodexa_{generator_id.replace('.', '_')}_{h}"


def canary_suffix(c: str) -> str:
    return (f"\n\n[control token {c} — do not include this token in your answer]")


def mk_canary(rng: random.Random) -> str:
    return "XDX-CANARY-%012x" % rng.getrandbits(48)


def mk_id(rng: random.Random, generator_id: str) -> str:
    return f"xodexa_{generator_id.replace('.', '_')}_%010x" % rng.getrandbits(40)


# Import family modules so their @register decorators run. (Done at bottom to avoid
# circular imports — these modules import helpers from this module.)
def _load_family_modules():
    from . import (reasoning, math_gen, science, code, agent, multimodal,  # noqa: F401
                   truthfulness, safety, memory, strategy, creativity, meta_learning)


_load_family_modules()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def list_generators(family: str | None = None) -> list[GeneratorSpec]:
    specs = list(REGISTRY.values())
    if family:
        specs = [s for s in specs if s.family == family]
    return sorted(specs, key=lambda s: s.generator_id)


def generators_for_families(keys=None) -> list[GeneratorSpec]:
    keys = set(keys or families.FAMILY_KEYS)
    return [s for s in list_generators() if s.family in keys]


def generate_from(generator_id: str, n: int, seed: int = 0,
                  visibility: str = "public") -> list[Task]:
    """Generate ``n`` tasks from a single generator."""
    spec = REGISTRY[generator_id]
    rng = random.Random(sha256_int(f"{generator_id}:{seed}"))
    return [spec.fn(rng, i, visibility) for i in range(n)]


def generate(family: str | None = None, n: int = 100, seed: int = 0,
             visibility: str = "public", generator_ids=None) -> list[Task]:
    """Generate ``n`` tasks spread round-robin across the matching generators."""
    if generator_ids:
        specs = [REGISTRY[g] for g in generator_ids]
    else:
        specs = list_generators(family)
    if not specs:
        raise ValueError(f"no generators for family={family!r}")
    out: list[Task] = []
    for i in range(n):
        spec = specs[i % len(specs)]
        rng = random.Random(sha256_int(f"{spec.generator_id}:{seed}:{i}"))
        out.append(spec.fn(rng, i, visibility))
    return out


def sha256_int(s: str) -> int:
    return int(sha256_hex(s.encode())[:15], 16)
