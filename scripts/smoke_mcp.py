"""End-to-end smoke test: drive tdf-mcp over real stdio with an MCP client.

This exercises the full wire protocol -- initialize handshake, tools/list,
tools/call -- against the server exactly as an MCP host would launch it.
Not part of CI (needs the mcp extra); run manually:

    .venv/bin/python scripts/smoke_mcp.py samples/runbook.md
"""

import asyncio
import json
import sys
from pathlib import Path


async def main(doc_path: str) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "tdf.mcp_server"], cwd=str(root)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print(f"TOOLS ({len(tools.tools)}):", sorted(t.name for t in tools.tools))

            async def call(name: str, args: dict) -> dict:
                res = await session.call_tool(name, args)
                texts = [c.text for c in res.content if getattr(c, "text", None)]
                raw = "\n".join(texts).strip()
                try:
                    return json.loads(raw)          # our tools return plain dicts
                except json.JSONDecodeError:
                    return {"_raw": raw}

            opened = await call("open_document", {"path": doc_path})
            payload = opened
            print("\n== open_document ==")
            print(json.dumps(payload.get("tokens", {}), indent=2))
            print("elisions:", [e["id"] for e in payload.get("elisions", [])])
            print("view head:\n" + payload.get("view", opened.get("_raw", ""))[:400])

            sections = payload.get("sections") or []
            if sections:
                sid = sections[min(1, len(sections) - 1)]["id"]
                sec = await call("read_section",
                                 {"path": doc_path, "section_ids": [sid]})
                sp = sec
                print(f"\n== read_section([{sid}]) == tokens:",
                      sp.get("tokens"), "| requested:", sp.get("requested"))

            elided = payload.get("elisions") or []
            if elided:
                exp = await call("expand_region",
                                 {"path": doc_path, "region_id": elided[0]["id"]})
                ep = exp
                print(f"\n== expand_region({elided[0]['id']}) == tokens:",
                      ep.get("tokens"), "| text head:", (ep.get("text") or "")[:80])
            else:
                print("\n== expand_region: no elisions here; error path exercised ==")
                err = await call("expand_region",
                                 {"path": doc_path, "region_id": "x999"})
                print(err)

            print("\nSMOKE OK")


if __name__ == "__main__":
    doc = sys.argv[1] if len(sys.argv) > 1 else "samples/runbook.md"
    asyncio.run(main(doc))