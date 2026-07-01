"""
xodexa.render
===============
Seeded, deterministic figure rendering for the multimodal task family. Each helper
turns plain data (labels/values/rows/edges) into REAL PNG bytes so multimodal tasks
can attach an actual image instead of a text proxy — the model must read the figure,
not the prompt.

Determinism contract (same inputs -> byte-identical PNG on the same Pillow build):
fixed 640x400 canvas, PIL's built-in bitmap font (no system fonts), fixed palette,
no timestamps or metadata chunks. That keeps task ``source_hash`` values and re-run
stability meaningful.

PIL is imported lazily INSIDE each render function so this module always imports —
air-gapped runners without Pillow see ``HAS_PIL = False`` and the generators fall
back to the legacy text-proxy rendering.
"""

from __future__ import annotations

import base64
import importlib.util
import io

# True when Pillow is importable. find_spec avoids importing PIL at module load.
HAS_PIL: bool = importlib.util.find_spec("PIL") is not None

# Fixed canvas + palette — part of the determinism contract, do not derive from env.
WIDTH, HEIGHT = 640, 400
BG = (255, 255, 255)
FG = (20, 20, 20)
BAR = (70, 110, 180)
LINE = (180, 70, 70)
NODE = (230, 240, 255)
GRID = (200, 200, 200)


def png_base64(png: bytes) -> str:
    """Base64-encode PNG bytes for embedding in a task's input_assets."""
    return base64.b64encode(png).decode("ascii")


def _canvas():
    """(img, draw, font) triple on the fixed canvas with the default bitmap font."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    return img, ImageDraw.Draw(img), ImageFont.load_default()


def _png(img) -> bytes:
    """Serialize deterministically: plain PNG, no metadata/timestamps."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def render_bar_chart(labels, values) -> bytes:
    """Vertical bar chart; each bar is annotated with its numeric value on top."""
    img, d, font = _canvas()
    n = len(values)
    vmax = max(values) or 1
    plot_l, plot_r, plot_t, plot_b = 60, WIDTH - 30, 40, HEIGHT - 50
    d.line([(plot_l, plot_b), (plot_r, plot_b)], fill=FG, width=2)  # x axis
    d.line([(plot_l, plot_t), (plot_l, plot_b)], fill=FG, width=2)  # y axis
    slot = (plot_r - plot_l) // n
    for i, (lab, v) in enumerate(zip(labels, values)):
        x0 = plot_l + i * slot + slot // 4
        x1 = plot_l + (i + 1) * slot - slot // 4
        h = int((plot_b - plot_t - 20) * (v / vmax))
        y0 = plot_b - h
        d.rectangle([x0, y0, x1, plot_b - 1], fill=BAR, outline=FG)
        d.text(((x0 + x1) // 2 - 8, y0 - 14), str(v), fill=FG, font=font)
        d.text(((x0 + x1) // 2 - 8, plot_b + 6), str(lab), fill=FG, font=font)
    return _png(img)


def render_line_chart(labels, values) -> bytes:
    """Line chart with labelled x-axis ticks and a dot at each data point."""
    img, d, font = _canvas()
    n = len(values)
    vmax, vmin = max(values), min(values)
    span = (vmax - vmin) or 1
    plot_l, plot_r, plot_t, plot_b = 60, WIDTH - 30, 40, HEIGHT - 50
    d.line([(plot_l, plot_b), (plot_r, plot_b)], fill=FG, width=2)
    d.line([(plot_l, plot_t), (plot_l, plot_b)], fill=FG, width=2)
    step = (plot_r - plot_l) / max(1, n - 1)
    pts = []
    for i, v in enumerate(values):
        x = int(plot_l + i * step)
        y = int(plot_b - 20 - (plot_b - plot_t - 40) * ((v - vmin) / span))
        pts.append((x, y))
        d.line([(x, plot_b - 3), (x, plot_b + 3)], fill=FG, width=1)  # tick
        d.text((x - 4, plot_b + 8), str(labels[i]), fill=FG, font=font)
    d.line(pts, fill=LINE, width=2)
    for x, y in pts:
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=LINE, outline=FG)
    return _png(img)


def render_table(rows) -> bytes:
    """Grid table; ``rows`` is a list of rows, each a list of cell strings. The first
    row is drawn as a shaded header."""
    img, d, font = _canvas()
    nrows = len(rows)
    ncols = max(len(r) for r in rows)
    x0, y0 = 40, 40
    cw = (WIDTH - 2 * x0) // ncols
    ch = min(40, (HEIGHT - 2 * y0) // nrows)
    for r, row in enumerate(rows):
        for c in range(ncols):
            cx, cy = x0 + c * cw, y0 + r * ch
            fill = (225, 225, 235) if r == 0 else BG
            d.rectangle([cx, cy, cx + cw, cy + ch], fill=fill, outline=GRID)
            cell = str(row[c]) if c < len(row) else ""
            d.text((cx + 8, cy + ch // 2 - 5), cell, fill=FG, font=font)
    return _png(img)


def render_node_diagram(edges) -> bytes:
    """Directed node diagram; ``edges`` is a list of (src, dst) node-name pairs.
    Nodes are laid out on a fixed circle in first-appearance order."""
    import math
    img, d, font = _canvas()
    nodes: list = []
    for a, b in edges:
        for name in (a, b):
            if name not in nodes:
                nodes.append(name)
    cx, cy, radius, r_node = WIDTH // 2, HEIGHT // 2, 140, 26
    pos = {}
    for i, name in enumerate(nodes):
        ang = -math.pi / 2 + 2 * math.pi * i / len(nodes)
        pos[name] = (int(cx + radius * math.cos(ang)), int(cy + radius * math.sin(ang)))
    for a, b in edges:  # edges first so circles sit on top
        d.line([pos[a], pos[b]], fill=FG, width=2)
    for name in nodes:
        x, y = pos[name]
        d.ellipse([x - r_node, y - r_node, x + r_node, y + r_node],
                  fill=NODE, outline=FG, width=2)
        d.text((x - 4 * len(str(name)) // 2 - 6, y - 5), str(name), fill=FG, font=font)
    return _png(img)
