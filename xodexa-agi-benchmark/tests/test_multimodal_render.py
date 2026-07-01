#!/usr/bin/env python3
"""
test_multimodal_render.py — contract tests for the REAL-image multimodal pipeline.

Covers: deterministic PNG rendering (xodexa.render), the img_* generators (schema
validity, satisfiable graders, no answer leaked in the prompt, decodable base64 PNG
assets, text-proxy fallback without PIL), and vision payload shapes for the
OpenAI-compatible and Anthropic connectors — including byte-identical backward
compatibility when assets=None.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))  # beat any shadow 'xodexa'

from xodexa import grade, render, runner, schema  # noqa: E402
from xodexa import generators as G  # noqa: E402
from xodexa.generators import multimodal_render  # noqa: E402,F401 — registers img_* gens

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
GIDS = ["multimodal.img_bar_max", "multimodal.img_line_trend",
        "multimodal.img_table_lookup", "multimodal.img_node_count"]

needs_pil = pytest.mark.skipif(not render.HAS_PIL, reason="Pillow not installed")


def _prompt_body(t):
    """Prompt minus the canary suffix (the canary hex can contain any digits)."""
    return t.prompt.split("\n\n[control token")[0]


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

@needs_pil
def test_rendering_is_deterministic():
    labels, values = ["Q1", "Q2", "Q3", "Q4"], [12, 87, 45, 33]
    rows = [["item", "value"], ["row1", "482"], ["row2", "917"]]
    edges = [("N1", "N2"), ("N2", "N3"), ("N3", "N4")]
    for fn, args in [(render.render_bar_chart, (labels, values)),
                     (render.render_line_chart, (list(range(1, 5)), values)),
                     (render.render_table, (rows,)),
                     (render.render_node_diagram, (edges,))]:
        a, b = fn(*args), fn(*args)
        assert a == b, f"{fn.__name__} not deterministic"
        assert a.startswith(PNG_MAGIC), f"{fn.__name__} did not produce a PNG"


@needs_pil
def test_png_base64_roundtrip():
    png = render.render_bar_chart(["A", "B"], [10, 20])
    assert base64.b64decode(render.png_base64(png)) == png


# --------------------------------------------------------------------------- #
# Generators
# --------------------------------------------------------------------------- #

def test_generators_registered_under_multimodal_family():
    ids = {s.generator_id for s in G.list_generators("multimodal")}
    assert set(GIDS) <= ids


def test_generators_valid_and_grader_satisfiable():
    for gid in GIDS:
        for t in G.generate_from(gid, 3, seed=7, visibility="public"):
            assert schema.is_valid(t), (gid, schema.validate_task(t))
            aw, mx, verdict = grade.grade(t.server_grader,
                                          grade.synth_good(t.server_grader),
                                          t.points, t.negative)
            assert mx and aw >= mx - 1e-6, (gid, aw, mx, verdict)


@needs_pil
def test_prompt_does_not_leak_answer():
    """The whole point of real images: the data lives in the PNG, not the prompt."""
    for gid in GIDS:
        for t in G.generate_from(gid, 5, seed=11, visibility="public"):
            body = _prompt_body(t)
            target = t.server_grader["target"]
            assert str(int(target)) not in body, (gid, target, body)
            assert str(target) not in body, (gid, target, body)


@needs_pil
def test_asset_is_real_decodable_png():
    for gid in GIDS:
        t = G.generate_from(gid, 1, seed=5, visibility="public")[0]
        assert len(t.input_assets) == 1
        a = t.input_assets[0]
        assert a["type"] == "image/png"
        assert a.get("rendered_inline") is False
        assert "fallback" not in a
        png = base64.b64decode(a["base64"])
        assert png.startswith(PNG_MAGIC)


def test_fallback_to_text_proxy_without_pil(monkeypatch):
    """With PIL 'unavailable', generators inline the data and mark the asset."""
    monkeypatch.setattr(multimodal_render, "HAS_PIL", False)
    for gid in GIDS:
        t = G.generate_from(gid, 1, seed=5, visibility="public")[0]
        a = t.input_assets[0]
        assert a.get("fallback") == "text"
        assert "base64" not in a
        assert "[FIGURE:" in t.prompt  # data restated as a text proxy
        assert schema.is_valid(t), schema.validate_task(t)
        aw, mx, _ = grade.grade(t.server_grader, grade.synth_good(t.server_grader),
                                t.points, t.negative)
        assert mx and aw >= mx - 1e-6


def test_same_seed_same_task_data():
    """rng-seeded generation stays reproducible (grader + prompt identical)."""
    for gid in GIDS:
        a = G.generate_from(gid, 2, seed=9, visibility="public")
        b = G.generate_from(gid, 2, seed=9, visibility="public")
        for x, y in zip(a, b):
            assert x.prompt == y.prompt
            assert x.server_grader == y.server_grader
            assert x.input_assets == y.input_assets


# --------------------------------------------------------------------------- #
# Connector payloads (fake transport — no network)
# --------------------------------------------------------------------------- #

def _capture_post(monkeypatch, response):
    captured = {}

    def fake_post(url, headers, payload, timeout):
        captured["url"], captured["payload"] = url, payload
        return response

    monkeypatch.setattr(runner, "_post_json", fake_post)
    return captured


_OPENAI_RESP = {"choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
_ANTHROPIC_RESP = {"content": [{"type": "text", "text": "ok"}],
                   "usage": {"input_tokens": 1, "output_tokens": 1}}
_ASSET = {"type": "image/png", "ref": "bar_chart", "base64": "QUJD",
          "rendered_inline": False}


def test_openai_payload_with_image_assets(monkeypatch):
    cap = _capture_post(monkeypatch, _OPENAI_RESP)
    conn = runner.OpenAICompatibleConnector("http://x/v1", "m", api_key="k")
    assert conn.complete("what is it?", assets=[_ASSET]) == "ok"
    content = cap["payload"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "what is it?"}
    assert content[1] == {"type": "image_url",
                          "image_url": {"url": "data:image/png;base64,QUJD"}}


def test_openai_payload_without_assets_is_byte_identical(monkeypatch):
    cap = _capture_post(monkeypatch, _OPENAI_RESP)
    conn = runner.OpenAICompatibleConnector("http://x/v1", "m", api_key="k")
    conn.complete("hi")
    legacy = {"model": "m", "messages": [{"role": "user", "content": "hi"}],
              "temperature": 0.0}
    assert cap["payload"] == legacy
    assert json.dumps(cap["payload"]).encode() == json.dumps(legacy).encode()
    # assets=None and assets=[] must also match the legacy wire bytes exactly
    for assets in (None, []):
        conn.complete("hi", assets=assets)
        assert json.dumps(cap["payload"]).encode() == json.dumps(legacy).encode()


def test_anthropic_payload_with_image_assets(monkeypatch):
    cap = _capture_post(monkeypatch, _ANTHROPIC_RESP)
    conn = runner.AnthropicConnector(api_key="k", model="claude-x")
    assert conn.complete("what is it?", assets=[_ASSET]) == "ok"
    content = cap["payload"]["messages"][0]["content"]
    assert content[0] == {"type": "image",
                          "source": {"type": "base64", "media_type": "image/png",
                                     "data": "QUJD"}}
    assert content[1] == {"type": "text", "text": "what is it?"}


def test_anthropic_payload_without_assets_is_byte_identical(monkeypatch):
    cap = _capture_post(monkeypatch, _ANTHROPIC_RESP)
    conn = runner.AnthropicConnector(api_key="k", model="claude-x")
    conn.complete("hi")
    legacy = {"model": "claude-x", "max_tokens": 4096, "temperature": 0,
              "messages": [{"role": "user", "content": "hi"}]}
    assert cap["payload"] == legacy
    assert json.dumps(cap["payload"]).encode() == json.dumps(legacy).encode()
    for assets in (None, []):
        conn.complete("hi", assets=assets)
        assert json.dumps(cap["payload"]).encode() == json.dumps(legacy).encode()


def test_assets_without_base64_are_ignored(monkeypatch):
    """Text-proxy fallback assets (no base64) must not switch payloads to vision."""
    cap = _capture_post(monkeypatch, _OPENAI_RESP)
    conn = runner.OpenAICompatibleConnector("http://x/v1", "m", api_key="k")
    conn.complete("hi", assets=[{"type": "image/png", "ref": "r",
                                 "rendered_inline": True, "fallback": "text"}])
    assert cap["payload"]["messages"][0]["content"] == "hi"


def test_callable_connector_asset_handling():
    one = runner.CallableConnector(lambda p: "got:" + p)
    assert one.complete("x", assets=[_ASSET]) == "got:x"  # extra arg ignored safely
    two = runner.CallableConnector(lambda p, a: f"{p}|{len(a or [])}")
    assert two.complete("x", assets=[_ASSET]) == "x|1"  # passed through
    assert two.complete("x") == "x|0"
