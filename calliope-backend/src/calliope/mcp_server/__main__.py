from __future__ import annotations

import logging
import os
import sys

import anyio
from mcp.server.stdio import stdio_server

from calliope.mcp_server.server import build_server

LOG_LEVEL_VARIABLE = "CALLIOPE_MCP_LOG_LEVEL"
DEFAULT_LOG_LEVEL = "WARNING"


async def serve() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    level = os.environ.get(LOG_LEVEL_VARIABLE, DEFAULT_LOG_LEVEL).upper()
    logging.basicConfig(stream=sys.stderr, level=level)
    anyio.run(serve)


if __name__ == "__main__":
    main()
