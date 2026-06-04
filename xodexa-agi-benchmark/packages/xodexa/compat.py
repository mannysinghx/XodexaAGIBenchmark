"""
xodexa.compat
===============
Backward compatibility layer. Older benchmark examples (and any third-party data)
may use ``category`` / ``subcategory`` fields instead of the canonical
``task_family`` / ``subdomain``. This module provides:

  * ``migrate_task_dict(d)``  — rewrite category/subcategory → task_family/subdomain
  * ``CATEGORY_MAP``          — the authoritative mapping table
  * ``normalize_split(s)``    — map old split names to the five-way canonical set
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Category → (task_family, subdomain) mapping table
# --------------------------------------------------------------------------- #

CATEGORY_MAP: dict[str, tuple[str, str]] = {
    # old_category: (task_family, subdomain)
    "direct_jailbreak":          ("jailbreak_resistance", "direct_jailbreak"),
    "roleplay_manipulation":     ("jailbreak_resistance", "roleplay_persona_escape"),
    "indirect_prompt_injection": ("rag_poisoning",        "indirect_rag_injection"),
    "prompt_injection":          ("safety",               "prompt_injection"),
    "system_prompt_extraction":  ("privacy_security",     "system_prompt_extraction"),
    "canary_leakage":            ("privacy_security",     "canary_leakage"),
    "tool_misuse":               ("tool_safety",          "unauthorized_tool_call"),
    "excessive_agency":          ("agentic_safety",       "excessive_agency"),
    "data_exfiltration":         ("tool_safety",          "data_exfiltration"),
    "rag_poisoning":             ("rag_poisoning",        "indirect_rag_injection"),
    "over_refusal":              ("over_refusal",         "benign_technical_question"),
    "benign_lookalike":          ("over_refusal",         "benign_security_education"),
    "multi_turn_manipulation":   ("multi_turn_manipulation", "gradual_escalation"),
    "authority_pressure":        ("jailbreak_resistance", "authority_pressure"),
    "social_engineering":        ("jailbreak_resistance", "authority_pressure"),
    "instruction_hierarchy":     ("safety",               "instruction_hierarchy"),
    "sycophancy":                ("safety",               "sycophancy"),
    "privacy":                   ("safety",               "privacy"),
    "privacy_boundary":          ("privacy_security",     "pii_exposure"),
}


# --------------------------------------------------------------------------- #
# Split name normalisation
# --------------------------------------------------------------------------- #

SPLIT_MAP: dict[str, str] = {
    "public":              "public_practice",
    "public_practice":     "public_practice",
    "private":             "private_official",
    "private_official":    "private_official",
    "rotating":            "rotating_adversarial",
    "rotating_adversarial":"rotating_adversarial",
    "live_generated":      "live_generated",
    "dynamic":             "live_generated",
    "agent":               "agent_environment",
    "agent_environment":   "agent_environment",
}


def normalize_split(s: str) -> str:
    """Map an old or new split name to the five-way canonical set.

    Returns the canonical name, or the original string if not found in the map
    (to allow forward-compatible unknown splits to pass through without crashing).
    """
    return SPLIT_MAP.get(s, s)


# --------------------------------------------------------------------------- #
# Task dict migration
# --------------------------------------------------------------------------- #

def migrate_task_dict(d: dict) -> dict:
    """Migrate a task dict that may use old field names to the canonical schema.

    Transformations applied:
      1. If ``task_family`` is already set, return ``d`` unchanged (idempotent).
      2. Look up ``category`` in CATEGORY_MAP; set ``task_family`` + ``subdomain``.
         - If ``subdomain`` is already set explicitly, prefer it over the map default.
         - If ``category`` is not in CATEGORY_MAP, use it verbatim as ``task_family``
           and copy ``subcategory`` (if any) to ``subdomain``.
      3. Normalize ``split`` via SPLIT_MAP if present.
      4. Remove obsolete fields: ``category``, ``subcategory``, ``attack_type``.

    Returns a new dict; the input is not mutated.
    """
    d = dict(d)  # shallow copy — do not mutate caller's dict

    # (1) Already canonical
    if d.get("task_family"):
        # Still normalize the split if present
        if "split" in d:
            d["split"] = normalize_split(d["split"])
        return d

    category = d.get("category", "")
    subcategory = d.get("subcategory", "")

    # (2) Look up in CATEGORY_MAP
    if category in CATEGORY_MAP:
        family, default_sub = CATEGORY_MAP[category]
        d["task_family"] = family
        # Prefer explicitly set subcategory over the map default
        d["subdomain"] = d.get("subdomain") or subcategory or default_sub
    else:
        # Unknown category — use as-is; at least we set task_family
        d["task_family"] = category or "safety"
        d["subdomain"] = d.get("subdomain") or subcategory or ""

    # (3) Normalize split
    if "split" in d:
        d["split"] = normalize_split(d["split"])

    # (4) Remove obsolete fields
    for old_field in ("category", "subcategory", "attack_type"):
        d.pop(old_field, None)

    return d
