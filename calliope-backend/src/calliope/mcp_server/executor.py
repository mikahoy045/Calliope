from __future__ import annotations

import json
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Mapping

from calliope.cli.context import CliContext
from calliope.cli.main import _patch
from calliope.cli.policy import check_op
from calliope.mcp_server.errors import RenderLossError, UsageError
from calliope.mcp_server.surface import (
    PAYLOAD_ARGUMENT,
    PAYLOAD_OPTION,
    RENDER_LOSS_ARGUMENT,
    Operation,
)

ACTOR = "mcp"
PAYLOAD_FILE_NAME = "payload.json"
REMOVED_ROW_KEYS = ("removed", "removed_clips")
PRODUCTION_COLUMNS = ("clip_path", "video_path", "env_image_path", "video_settings_json")

_parse_lock = threading.Lock()


def execute(operation: Operation, arguments: Mapping[str, Any] | None) -> Any:
    supplied = _supplied(operation, arguments)
    allows_render_loss = _switch(RENDER_LOSS_ARGUMENT, supplied.pop(RENDER_LOSS_ARGUMENT, False))
    with ExitStack() as stack:
        argv, given = _command_line(operation, supplied, stack)
        if operation.removes_rows and not allows_render_loss:
            _refuse_render_loss(_dispatch(operation, argv, given, preview=True))
        return _dispatch(operation, argv, given, preview=False)


def _supplied(operation: Operation, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied = {name: value for name, value in dict(arguments or {}).items() if value is not None}
    allowed = operation.argument_names
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise UsageError(f"{operation.name} has no argument {unknown}; it takes {sorted(allowed)}")
    missing = [name for name in operation.required_names if name not in supplied]
    if missing:
        raise UsageError(f"{operation.name} needs {missing}")
    return supplied


def _command_line(
    operation: Operation, supplied: Mapping[str, Any], stack: ExitStack
) -> tuple[list[str], frozenset[str]]:
    argv: list[str] = []
    given: set[str] = set()
    for argument in operation.arguments:
        if argument.name not in supplied:
            continue
        value = supplied[argument.name]
        if argument.is_switch:
            if _switch(argument.name, value):
                argv.append(argument.option)
                given.add(argument.option)
            continue
        argv.append(f"{argument.option}={_text(argument.name, value)}")
        given.add(argument.option)
    if PAYLOAD_ARGUMENT in supplied:
        folder = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        payload_file = folder / PAYLOAD_FILE_NAME
        payload_file.write_text(
            json.dumps(_payload(supplied[PAYLOAD_ARGUMENT]), ensure_ascii=False),
            encoding="utf-8",
        )
        argv.append(f"{PAYLOAD_OPTION}={payload_file}")
    return argv, frozenset(given)


def _switch(name: str, value: Any) -> bool:
    if not isinstance(value, bool):
        raise UsageError(f"{name} must be true or false")
    return value


def _text(name: str, value: Any) -> str:
    if isinstance(value, bool):
        raise UsageError(f"{name} does not take true or false")
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, (list, tuple)):
        return ",".join(_text(name, item) for item in value)
    raise UsageError(f"{name} must be text, a number or a list of them")


def _payload(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise UsageError(f"payload is text that is not valid JSON: {error.msg}") from error


def _dispatch(
    operation: Operation, argv: list[str], given: frozenset[str], *, preview: bool
) -> Any:
    with _parse_lock:
        namespace = operation.parser.parse_args(argv)
    context = CliContext(dry_run=preview or getattr(namespace, "dry_run", False), actor=ACTOR)
    try:
        check_op(operation.group, operation.verb, writes=operation.writes)
        namespace._given = given
        namespace.patch = _patch(namespace)
        return namespace._handler(context, namespace)
    finally:
        context.close()


def _refuse_render_loss(preview: Any) -> None:
    if not isinstance(preview, Mapping):
        return
    at_risk: dict[str, list[dict[str, Any]]] = {}
    for key in REMOVED_ROW_KEYS:
        rows = [_production_state(row) for row in preview.get(key) or []]
        held = [row for row in rows if row["holds"]]
        if held:
            at_risk[key] = held
    if at_risk:
        raise RenderLossError(at_risk)


def _production_state(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "order_index": row.get("order_index"),
        "holds": [column for column in PRODUCTION_COLUMNS if row.get(column)],
    }
