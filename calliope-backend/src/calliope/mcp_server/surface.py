from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from typing import Any, NoReturn

from calliope.authoring.models import INPUT_MODELS
from calliope.cli.main import build_parser
from calliope.mcp_server import descriptions
from calliope.mcp_server.errors import UsageError

PAYLOAD_ARGUMENT = "payload"
PAYLOAD_OPTION = "--file"
RENDER_LOSS_ARGUMENT = "allow_render_loss"
DRY_RUN_OPTION = "--dry-run"
PROJECT_OPTION = "--project"
SCENE_OPTION = "--scene"
SCENE_GROUP = "clips"
TRANSPORT_OPTIONS = frozenset({"--help", "--json", "--idea-file", PAYLOAD_OPTION})
IMAGE_OPTIONS = frozenset(
    {
        "--consistency-prompt",
        "--portrait-path",
        "--sheet-path",
        "--reference-image-path",
        "--cover-path",
    }
)
HIDDEN_OPTIONS = TRANSPORT_OPTIONS | IMAGE_OPTIONS
PROJECTLESS_OPERATIONS = frozenset({("project", "list")})
PROJECT_OPTIONAL_OPERATIONS = frozenset({("log", "list"), ("clips", "list")})
ROW_REMOVING_VERBS = frozenset({"replace-range"})
FLAGS_ONLY = "none"
SINGLE_DOCUMENT = "object"
JSON_TYPES = {int: "integer", float: "number"}
DEFINITIONS_KEY = "$defs"


@dataclass(frozen=True)
class Argument:
    name: str
    option: str
    schema: dict[str, Any]
    required: bool
    is_switch: bool


@dataclass(frozen=True)
class Operation:
    group: str
    verb: str
    writes: bool
    parser: argparse.ArgumentParser
    arguments: tuple[Argument, ...]
    payload_schema: dict[str, Any] | None
    payload_required: bool

    @property
    def name(self) -> str:
        return f"{self.group}_{self.verb}".replace("-", "_")

    @property
    def removes_rows(self) -> bool:
        return self.verb in ROW_REMOVING_VERBS

    @property
    def description(self) -> str:
        return descriptions.tool_description(self.group, self.verb, self.writes)

    @property
    def argument_names(self) -> frozenset[str]:
        return frozenset(self.input_schema()["properties"])

    @property
    def required_names(self) -> tuple[str, ...]:
        return tuple(self.input_schema()["required"])

    def input_schema(self) -> dict[str, Any]:
        properties = {argument.name: argument.schema for argument in self.arguments}
        required = [argument.name for argument in self.arguments if argument.required]
        schema: dict[str, Any] = {"type": "object"}
        if self.payload_schema is not None:
            payload = copy.deepcopy(self.payload_schema)
            definitions = _take_definitions(payload)
            if definitions:
                schema[DEFINITIONS_KEY] = definitions
            properties[PAYLOAD_ARGUMENT] = payload
            if self.payload_required:
                required.append(PAYLOAD_ARGUMENT)
        if self.removes_rows:
            properties[RENDER_LOSS_ARGUMENT] = {
                "type": "boolean",
                "description": descriptions.RENDER_LOSS,
            }
        return {
            **schema,
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }


def load_operations() -> tuple[Operation, ...]:
    operations = [
        _operation(group, verb, verb_parser)
        for group, group_parser in _subparsers(build_parser()).items()
        for verb, verb_parser in _subparsers(group_parser).items()
    ]
    return tuple(operations)


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _operation(group: str, verb: str, parser: argparse.ArgumentParser) -> Operation:
    parser.error = _reject_usage
    writes = bool(parser.get_default("_write"))
    options = [action for action in parser._actions if action.option_strings]
    visible = [action for action in options if _is_visible(group, verb, writes, action)]
    file_option = next(
        (action for action in options if PAYLOAD_OPTION in action.option_strings), None
    )
    payload_schema, payload_required = _payload(group, verb, file_option)
    return Operation(
        group=group,
        verb=verb,
        writes=writes,
        parser=parser,
        arguments=tuple(_argument(action, _is_required(group, verb, action)) for action in visible),
        payload_schema=payload_schema,
        payload_required=payload_required,
    )


def _reject_usage(message: str) -> NoReturn:
    raise UsageError(message)


def _is_visible(group: str, verb: str, writes: bool, action: argparse.Action) -> bool:
    names = frozenset(action.option_strings)
    if names & HIDDEN_OPTIONS:
        return False
    if DRY_RUN_OPTION in names:
        return writes
    if SCENE_OPTION in names:
        return group == SCENE_GROUP
    if PROJECT_OPTION in names:
        return (group, verb) not in PROJECTLESS_OPERATIONS
    return True


def _is_required(group: str, verb: str, action: argparse.Action) -> bool:
    names = frozenset(action.option_strings)
    if SCENE_OPTION in names:
        return True
    if PROJECT_OPTION in names:
        return (group, verb) not in PROJECT_OPTIONAL_OPERATIONS
    return bool(action.required)


def _argument(action: argparse.Action, required: bool) -> Argument:
    is_switch = action.nargs == 0
    schema: dict[str, Any] = {
        "type": "boolean" if is_switch else JSON_TYPES.get(action.type, "string")
    }
    if action.choices:
        schema["enum"] = list(action.choices)
    if not is_switch and action.default not in (None, argparse.SUPPRESS):
        schema["default"] = action.default
    cli_help = None if action.help == argparse.SUPPRESS else action.help
    text = descriptions.argument_description(action.dest, cli_help)
    if text:
        schema["description"] = text
    return Argument(
        name=action.dest,
        option=action.option_strings[-1],
        schema=schema,
        required=required,
        is_switch=is_switch,
    )


def _payload(
    group: str, verb: str, file_option: argparse.Action | None
) -> tuple[dict[str, Any] | None, bool]:
    entry = INPUT_MODELS.get(group, {}).get(verb)
    if entry is None:
        if file_option is None:
            return None, False
        open_schema = {
            "type": ["array", "object"],
            "description": descriptions.PAYLOAD_ANY,
        }
        return open_schema, bool(file_option.required)
    model, accepts = entry
    if accepts == FLAGS_ONLY:
        return None, False
    row = model.model_json_schema()
    if accepts == SINGLE_DOCUMENT:
        return {**row, "description": descriptions.PAYLOAD_DOCUMENT}, True
    rows = {
        "type": "array",
        "minItems": 1,
        "items": row,
        "description": descriptions.PAYLOAD_ROWS,
    }
    return rows, True


def _take_definitions(payload: dict[str, Any]) -> dict[str, Any]:
    holders = [payload, payload.get("items")]
    definitions: dict[str, Any] = {}
    for holder in holders:
        if isinstance(holder, dict):
            definitions.update(holder.pop(DEFINITIONS_KEY, {}))
    return definitions
