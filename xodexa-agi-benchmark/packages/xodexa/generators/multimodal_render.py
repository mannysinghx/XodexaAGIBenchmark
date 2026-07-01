"""Multimodal-family generators backed by REAL rendered PNG figures (xodexa.render).
Unlike generators/multimodal.py (text-rendered proxies), these attach an actual
base64 PNG in ``input_assets`` and the prompt deliberately does NOT restate the
figure's data — the model must read the image. Graders stay exact (numeric) because
they are computed from the same seeded data that was rendered.

If Pillow is unavailable (``render.HAS_PIL`` is False, e.g. an air-gapped runner),
each generator degrades to the legacy text-proxy style — data inlined in the prompt,
no base64 — and marks the asset dict with ``{"fallback": "text"}`` so nothing breaks."""

from __future__ import annotations

from . import register, mk_canary, mk_id, canary_suffix
from ..render import (HAS_PIL, png_base64, render_bar_chart, render_line_chart,
                      render_node_diagram, render_table)
from ..schema import new_task

_GID = "multimodal."


def _img_asset(ref, png):
    return [{"type": "image/png", "ref": ref, "base64": png_base64(png),
             "rendered_inline": False}]


def _text_asset(ref):
    # Text-proxy fallback: the "figure" is inlined in the prompt (no image bytes).
    return [{"type": "image/png", "ref": ref, "rendered_inline": True,
             "fallback": "text"}]


def _mk(gid, sub, prompt, atype, grader, ans, rng, *, diff, pts=3, neg=1, vis, asset):
    c = mk_canary(rng)
    return new_task(mk_id(rng, gid), "multimodal", sub, prompt + canary_suffix(c), atype,
                    server_grader=grader, expected_answer=ans, difficulty=diff,
                    visibility=vis, points=pts, negative=neg, canary=c,
                    modality=["image", "text"], input_assets=asset)


@register(_GID + "img_bar_max", "multimodal")
def img_bar_max(rng, idx, vis):
    """Read the tallest bar's value off a rendered bar chart PNG."""
    cats = rng.sample(["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"], 4)
    vals = rng.sample(range(10, 99), 4)
    mx = max(vals)
    if HAS_PIL:
        p = ("Look at the attached image. It is a bar chart; each bar is labelled "
             "with its value. What is the value of the tallest bar? Give only the "
             "number.")
        asset = _img_asset("bar_chart", render_bar_chart(cats, vals))
    else:
        table = "\n".join(f"  {c}: {'#' * (v // 5)} ({v})" for c, v in zip(cats, vals))
        p = ("[FIGURE: bar chart]\n" + table + "\n\nWhich value is the maximum bar "
             "height? Give only the number.")
        asset = _text_asset("bar_chart")
    return _mk(_GID + "img_bar_max", "chart_qa", p, "numeric",
               {"type": "numeric", "target": float(mx), "tolerance": 0.001}, mx,
               rng, diff=3.0, vis=vis, asset=asset)


@register(_GID + "img_line_trend", "multimodal")
def img_line_trend(rng, idx, vis):
    """Locate the peak of a rendered line chart PNG (x position of the maximum)."""
    xs = list(range(1, 9))
    vals = rng.sample(range(10, 80), 8)
    peak = rng.randint(2, 7)
    vals[peak - 1] = 95  # unambiguous single maximum
    if HAS_PIL:
        p = ("Look at the attached image. It is a line chart; the x-axis ticks are "
             "numbered. At which x-axis position does the line reach its highest "
             "point? Give only the number.")
        asset = _img_asset("line_chart", render_line_chart(xs, vals))
    else:
        series = ", ".join(f"x={x}: {v}" for x, v in zip(xs, vals))
        p = ("[FIGURE: line chart]\n  " + series + "\n\nAt which x value does the "
             "line reach its highest point? Give only the number.")
        asset = _text_asset("line_chart")
    return _mk(_GID + "img_line_trend", "chart_qa", p, "numeric",
               {"type": "numeric", "target": float(peak), "tolerance": 0.001}, peak,
               rng, diff=3.5, vis=vis, asset=asset)


@register(_GID + "img_table_lookup", "multimodal")
def img_table_lookup(rng, idx, vis):
    """Look up one cell in a rendered data-table PNG."""
    rows = {f"row{i}": rng.randint(100, 999) for i in range(1, 5)}
    key = rng.choice(list(rows))
    if HAS_PIL:
        p = (f"Look at the attached image. It is a data table. What is the value in "
             f"the row labelled '{key}'? Give only the number.")
        grid = [["item", "value"]] + [[k, str(v)] for k, v in rows.items()]
        asset = _img_asset("data_table", render_table(grid))
    else:
        table = "\n".join(f"  {k} | value={v}" for k, v in rows.items())
        p = ("[FIGURE: data table]\n" + table + f"\n\nWhat is the value for {key}? "
             "Give only the number.")
        asset = _text_asset("data_table")
    return _mk(_GID + "img_table_lookup", "table_extract", p, "numeric",
               {"type": "numeric", "target": float(rows[key]), "tolerance": 0.001},
               rows[key], rng, diff=3.5, vis=vis, asset=asset)


@register(_GID + "img_node_count", "multimodal")
def img_node_count(rng, idx, vis):
    """Count the nodes in a rendered node-diagram PNG."""
    n = rng.randint(3, 8)
    names = [f"N{i}" for i in range(1, n + 1)]
    edges = list(zip(names, names[1:]))
    if HAS_PIL:
        p = ("Look at the attached image. It is a node diagram. How many nodes does "
             "it contain? Give only the number.")
        asset = _img_asset("node_diagram", render_node_diagram(edges))
    else:
        diagram = " -> ".join(f"[{x}]" for x in names)
        p = ("[FIGURE: node diagram]\n  " + diagram + "\n\nHow many nodes are in the "
             "diagram? Give only the number.")
        asset = _text_asset("node_diagram")
    return _mk(_GID + "img_node_count", "diagram", p, "numeric",
               {"type": "numeric", "target": float(n), "tolerance": 0.001}, n,
               rng, diff=2.5, vis=vis, asset=asset)
