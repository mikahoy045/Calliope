from __future__ import annotations

import json
import logging
from typing import Any

import anyio
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)

from calliope import __version__
from calliope.mcp_server import descriptions
from calliope.mcp_server.errors import INTERNAL, error_report
from calliope.mcp_server.executor import execute
from calliope.mcp_server.surface import Operation, load_operations

SERVER_NAME = "calliope"

logger = logging.getLogger("calliope.mcp_server")


def build_server() -> Server[Any]:
    operations = {operation.name: operation for operation in load_operations()}
    tools = [_tool(operation) for operation in operations.values()]

    async def list_tools(
        context: ServerRequestContext[Any], params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    async def call_tool(
        context: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult:
        operation = operations.get(params.name)
        if operation is None:
            raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")
        try:
            result = await anyio.to_thread.run_sync(execute, operation, params.arguments)
        except Exception as error:
            report = error_report(error)
            if report["kind"] == INTERNAL:
                logger.exception("tool %s failed", params.name)
            return _result(report, is_error=True)
        return _result(result, is_error=False)

    return Server(
        SERVER_NAME,
        version=__version__,
        instructions=descriptions.instructions(),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def _tool(operation: Operation) -> Tool:
    return Tool(
        name=operation.name,
        description=operation.description,
        input_schema=operation.input_schema(),
        annotations=ToolAnnotations(
            read_only_hint=not operation.writes,
            destructive_hint=True if operation.removes_rows else None,
            open_world_hint=False,
        ),
    )


def _result(body: Any, *, is_error: bool) -> CallToolResult:
    text = json.dumps(body, ensure_ascii=False, default=str)
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=is_error)
