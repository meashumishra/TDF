"""Tests for the lazy-context service behind the MCP server.

These target tdf.context_service directly -- no MCP SDK required -- because
the protocol layer is deliberately thin (see mcp_server.create_server, whose
tool registration is checked separately, skipped when the optional dependency
is absent).

Run: .venv/bin/python -m pytest tests/test_context_service.py -q
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tdf import context_service as svc  # noqa: E402
from tdf.tokens import count  # noqa: E402


NAV_WORDS = " ".join(f"entry{i}" for i in range(200))  # 200 tok, no sentences


@pytest.fixture()
def handbook(tmp_path):
    p = tmp_path / "handbook.md"
    p.write_text(
        "# Handbook\n\n"
        "## Overview\n\n"
        "Welcome prose. It has sentences.\n\n"
        f"## Navigation Index\n\n- {NAV_WORDS}\n\n"
        "## Details\n\n"
        "Specific operational content. Second sentence.\n",
        encoding="utf-8")
    yield p


@pytest.fixture(autouse=True)
def _clean_cache():
    svc.clear_cache()
    yield
    svc.clear_cache()


def _section_by_title(res: dict, title: str) -> dict:
    return next(s for s in res["sections"] if s["title"] == title)


# ---------------------------------------------------------------- open_document


def test_open_document_reports_views_and_declared_elisions(handbook):
    res = svc.open_document(handbook)

    assert res["title"] == "Handbook"
    tok = res["tokens"]
    assert all(isinstance(v, int) and v > 0 for v in tok.values())
    # The lazy view must actually be lazy: strictly cheaper than full Markdown.
    assert tok["this_view"] < tok["markdown_full"]

    # The nav blob is declared, never pasted: an !E line with exact accounting.
    assert "!E x1 index" in res["view"]
    el = res["elisions"]
    assert len(el) == 1 and el[0]["id"] == "x1"
    assert el[0]["tokens"] == count(NAV_WORDS)
    assert el[0]["items"] == 200  # gist item count from tier._gist


def test_open_document_is_deterministic_across_calls(handbook):
    first = svc.open_document(handbook)
    second = svc.open_document(handbook)  # served from cache
    assert first["elisions"] == second["elisions"]
    assert first["tokens"] == second["tokens"]
    assert first["view"] == second["view"]


def test_cache_invalidates_when_file_changes(handbook):
    before = svc.open_document(handbook)

    handbook.write_text(
        "# Handbook v2\n\n## Fresh Section\n\nDifferent content entirely. Yes.\n",
        encoding="utf-8")
    stat = handbook.stat()
    os.utime(handbook, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    after = svc.open_document(handbook)
    assert after["title"] == "Handbook v2"
    assert after["elisions"] == []          # nothing index-like any more
    assert before["title"] != after["title"]


# ---------------------------------------------------------------- expand_region


def test_expand_region_returns_verbatim_text_with_exact_tokens(handbook):
    opened = svc.open_document(handbook)
    res = svc.expand_region(handbook, "x1")

    assert res.get("id") == "x1"
    assert res["text"] == NAV_WORDS                     # verbatim, no '- ' marker
    assert res["tokens"] == opened["elisions"][0]["tokens"]  # promise kept


def test_expand_region_unknown_id_is_data_not_exception(handbook):
    res = svc.expand_region(handbook, "x99")
    assert "error" in res
    assert res["available"] == ["x1"]


# ----------------------------------------------------------------- read_section


def test_read_section_fetches_only_the_requested_subtree(handbook):
    details = _section_by_title(svc.open_document(handbook), "Details")
    res = svc.read_section(handbook, [details["id"]])

    assert res["requested"] == [details["id"]]
    assert "Specific operational content" in res["text"]
    assert "Welcome prose" not in res["text"]
    assert res["tokens"] == count(res["text"])          # self-accounting
    assert details["id"] in res["available_sections"]


def test_read_section_parent_id_pulls_children(tmp_path):
    p = tmp_path / "nested.md"
    p.write_text(
        "# Doc\n\n## Parent\n\nParent intro sentence.\n\n"
        "### Child\n\nChild body sentence.\n",
        encoding="utf-8")
    parent = _section_by_title(svc.open_document(p), "Parent")

    got = svc.read_section(p, [parent["id"]])
    assert "Child body sentence." in got["text"], (
        "parent id must include child sections (extract_sections rule)")


def test_read_section_unknown_ids_error_lists_available(handbook):
    res = svc.read_section(handbook, ["9"])
    assert "error" in res
    assert res["available"], "available section ids must be listed"


# --------------------------------------------------------------- diff_documents


def test_diff_documents_returns_minimal_structural_delta(handbook):
    v2 = handbook.with_name("handbook_v2.md")
    v2.write_text(handbook.read_text(encoding="utf-8").replace(
        "Specific operational content.", "REVISED operational content."),
        encoding="utf-8")

    res = svc.diff_documents(handbook, v2)
    assert res["diff"].startswith("!DIFF")
    assert "REVISED" in res["diff"]
    assert "entry199" not in res["diff"]   # unchanged content stays out
    assert 0 <= res["saved_pct"] <= 100
    assert res["tokens_diff"] < res["tokens_new_document_markdown"]
    v2.unlink()


# ------------------------------------------------------------ MCP registration


def test_mcp_server_registers_all_four_tools():
    pytest.importorskip("mcp")
    import asyncio

    from tdf.mcp_server import create_server

    tools = asyncio.run(create_server().list_tools())
    names = {t.name for t in tools}
    assert {"open_document", "expand_region", "read_section",
            "diff_documents"} <= names
    # Schemas must accept what the service functions accept: every tool takes
    # a path (or old/new pair) plus an optional max_pages.
    for t in tools:
        props = t.input_schema.get("properties", {})
        assert "path" in props or "old_path" in props, t.name