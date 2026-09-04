"""Check that the PowerMCP PSCAD server starts and exposes tools."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[2]


async def main() -> int:
    env = os.environ.copy()
    env["POWERIO_MCP_ALLOWED_ROOTS"] = str(ROOT)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "powermcp", "run", "pscad"],
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            init = await session.initialize()
            tools = await session.list_tools()
    server_info = getattr(init, "serverInfo", None) or getattr(init, "server_info", None)
    print(f"server: {server_info}")
    print(f"tool_count: {len(tools.tools)}")
    for tool in tools.tools:
        print(tool.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
