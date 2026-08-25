"""MCP server: serve TDF documents to agents as lazy, self-accounting context.

The loop this closes: a converter today pastes whole documents into context;
TDF's tier/skeleton/diff machinery already knows how to show a map instead of
the territory, declare what was left out, and fetch regions on demand. This
server exposes exactly those moves as MCP tools so *the model itself* can
navigate:

- ``open_document``  -- skeleton navigation, declared ``!E`` omissions, exact
  token cost of every view (the agent decides from numbers).
- ``expand_region``  -- resolve one ``!E`` id to its verbatim text.
- ``read_section``   -- expand chosen skeleton sections by id.
- ``diff_documents`` -- structural ``!DIFF`` between two versions, the
  minimal-delta update that avoids re-reading anything unchanged.

Run ``tdf-mcp`` (stdio transport) and register it in your MCP client config.
Requires the optional dependency: pip install 'tdf-converter[mcp]'
"""

from __future__ import annotations

import sys

from . import context_service as svc


def create_server():
    """Build the MCPServer instance with every tool registered. Separated from
    main() so tests can inspect registrations without opening stdio."""
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="tdf",
        instructions=(
            "Lazy document context server. Call open_document first: it returns "
            "the navigation skeleton with section ids, the list of elided "
            "index-like regions (!E), and exact token costs per view. Fetch "
            "only what you need via read_section / expand_region; use "
            "diff_documents to update on a new version instead of re-reading."
        ),
    )

    def _open_document(path: str, max_pages: int | None = None) -> dict:
        return svc.open_document(path, max_pages=max_pages)

    def _expand_region(path: str, region_id: str,
                       max_pages: int | None = None) -> dict:
        return svc.expand_region(path, region_id, max_pages=max_pages)

    def _read_section(path: str, section_ids: list[str],
                      max_pages: int | None = None) -> dict:
        return svc.read_section(path, section_ids, max_pages=max_pages)

    def _diff_documents(old_path: str, new_path: str,
                        summary_only: bool = False,
                        max_pages: int | None = None) -> dict:
        return svc.diff_documents(old_path, new_path,
                                   summary_only=summary_only,
                                   max_pages=max_pages)

    server.add_tool(
        _open_document, name="open_document",
        description="Open a document LAZILY. Returns the navigation skeleton "
                    "(section ids + token costs), the list of elided "
                    "index-like regions (!E ids), and exact token counts per "
                    "view. Do NOT request the whole document: call "
                    "read_section / expand_region for just what you need.")
    server.add_tool(
        _expand_region, name="expand_region",
        description="Fetch the verbatim text behind one elided region id "
                    "(e.g. 'x3') reported by open_document. You pay exactly "
                    "the declared token count.")
    server.add_tool(
        _read_section, name="read_section",
        description="Fetch specific sections by their skeleton id ('2' also "
                    "pulls 2.x children). Returns TDF-encoded text (no "
                    "legend) plus its exact token count.")
    server.add_tool(
        _diff_documents, name="diff_documents",
        description="Structural diff of two versions of a document (!DIFF "
                    "format): changed blocks/rows only, so you update your "
                    "understanding without re-reading unchanged content.")
    return server


def main() -> int:
    try:
        from mcp.server.mcpserver import MCPServer  # noqa: F401
    except ImportError:
        print("tdf-mcp requires the 'mcp' package. "
              "Install with: pip install 'tdf-converter[mcp]'",
              file=sys.stderr)
        return 1

    server = create_server()
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())