"""Multimodal-family generators (MVP text-rendered proxies). Real deployments attach
image/figure assets; here the 'figure' is rendered as a deterministic text table or
ASCII chart referenced via input_assets, so the grader stays exact while the task
shape (read a value off a figure, extract a table, spot a visual contradiction)
matches the multimodal contract. modality includes 'image' to mark the intent."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..schema import new_task

_GID = "multimodal."


def _asset(kind, ref):
    return [{"type": kind, "ref": ref, "rendered_inline": True}]


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=1, vis, asset):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "multimodal", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c,
                    modality=["image", "text"], input_assets=asset)


@register(_GID + "chart_read_max", "multimodal")
def chart_read_max(rng, idx, vis):
    """Read the maximum value off a (text-rendered) bar chart."""
    cats = rng.sample(["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"], 4)
    vals = rng.sample(range(10, 99), 4)
    table = "\n".join(f"  {c}: {'#' * (v // 5)} ({v})" for c, v in zip(cats, vals))
    mx = max(vals)
    p = ("[FIGURE: bar chart]\n" + table + "\n\nWhich value is the maximum bar height? "
         "Give only the number.")
    return _mk(_GID + "chart_read_max", "chart_qa", p, "numeric",
               {"type": "numeric", "target": float(mx), "tolerance": 0.001}, mx,
               rng, diff=3.0, vis=vis, asset=_asset("image/png", "bar_chart"))


@register(_GID + "table_extract", "multimodal")
def table_extract(rng, idx, vis):
    """Extract a specific cell as structured JSON."""
    rows = {f"row{i}": rng.randint(100, 999) for i in range(1, 5)}
    key = rng.choice(list(rows))
    table = "\n".join(f"  {k} | value={v}" for k, v in rows.items())
    p = ("[FIGURE: data table]\n" + table + f"\n\nReturn a JSON object {{\"key\": \"{key}\", "
         f"\"value\": <the value for {key}>}}.")
    g = {"type": "structured_json", "expect": {"key": key, "value": rows[key]}}
    return _mk(_GID + "table_extract", "table_extract", p, "structured_json", g,
               {"key": key, "value": rows[key]}, rng, diff=3.5, vis=vis,
               asset=_asset("image/png", "data_table"))


@register(_GID + "visual_contradiction", "multimodal")
def visual_contradiction(rng, idx, vis):
    """Spot two conflicting figures and report both."""
    a = rng.randint(100, 400)
    b = a + rng.randint(30, 120)
    p = (f"[FIGURE: report page] The header chart states total sales = {a} units. The "
         f"footnote table states total sales = {b} units.\n\nThese figures conflict. "
         f"State that the document is internally contradictory and give BOTH numbers.")
    g = {"type": "contains_all", "terms": [str(a), str(b)], "allow_partial": True}
    return _mk(_GID + "visual_contradiction", "visual_contradiction", p, "rubric", g,
               f"Contradiction: {a} vs {b}.", rng, diff=4.5, pts=4, neg=2, vis=vis,
               asset=_asset("image/png", "report_page"))


@register(_GID + "diagram_count", "multimodal")
def diagram_count(rng, idx, vis):
    """Count elements in a text-rendered diagram."""
    n = rng.randint(3, 8)
    diagram = " -> ".join(f"[node{i}]" for i in range(1, n + 1))
    p = ("[FIGURE: flow diagram]\n  " + diagram + "\n\nHow many nodes are in the diagram? "
         "Give only the number.")
    return _mk(_GID + "diagram_count", "diagram", p, "numeric",
               {"type": "numeric", "target": float(n), "tolerance": 0.001}, n,
               rng, diff=2.5, vis=vis, asset=_asset("image/png", "flow_diagram"))
