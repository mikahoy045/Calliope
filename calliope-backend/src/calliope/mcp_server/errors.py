from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import ValidationError

from calliope.authoring.service import AuthoringError, OrderingError
from calliope.cli.io import (
    EXIT_DRIFT,
    EXIT_NOT_FOUND,
    EXIT_POLICY,
    EXIT_VALIDATION,
    exit_code_for,
    problem_report,
)

VALIDATION = "validation"
DRIFT = "drift"
NOT_FOUND = "not_found"
POLICY = "policy"
ORDERING = "ordering"
RENDER_LOSS = "render_loss"
DATABASE = "database"
INTERNAL = "internal"

KIND_BY_EXIT_CODE = {
    EXIT_VALIDATION: VALIDATION,
    EXIT_DRIFT: DRIFT,
    EXIT_NOT_FOUND: NOT_FOUND,
    EXIT_POLICY: POLICY,
}

NEXT_STEPS = {
    VALIDATION: "Fix the arguments or the payload and call again. Nothing was written.",
    DRIFT: (
        "The rows changed since you read them, usually because the user edited them "
        "in the web UI. Call project_hash and read the rows again, then re-apply "
        "your change on top of what is there now."
    ),
    NOT_FOUND: "Check the id or name with the matching list tool. Nothing was written.",
    POLICY: "This action is not available through these tools. Do not look for another way.",
    ORDERING: (
        "Nothing was written. Positions must form a gapless sequence that starts at 1. "
        "Check the positions you passed against the matching list tool. If the message "
        "is about the stored scene order, the web UI left gaps in it, as it does when a "
        "scene is deleted: script_update on one scene with order_index set to its place "
        "in script_list, counted from 1, renumbers the scenes without changing their "
        "content. Then call again."
    ),
    RENDER_LOSS: (
        "Nothing was written. The listed rows hold renders or saved video settings "
        "made in the web UI. Tell the user exactly which rows would be lost. Call "
        "again with allow_render_loss set to true only after the user agrees, or "
        "use an update tool to change the text and keep the rows."
    ),
    DATABASE: "The database was busy or unavailable. Nothing was written. Try once more.",
    INTERNAL: "Unexpected failure. Nothing was written unless a later read shows otherwise.",
}

RENDER_LOSS_MESSAGE = "this write would remove rows that hold renders or saved video settings"


class UsageError(Exception):
    pass


class RenderLossError(Exception):
    def __init__(self, rows: dict[str, list[dict[str, Any]]]):
        super().__init__(RENDER_LOSS_MESSAGE)
        self.rows = rows


def error_kind(error: Exception) -> str:
    if isinstance(error, RenderLossError):
        return RENDER_LOSS
    if isinstance(error, OrderingError):
        return ORDERING
    if isinstance(error, AuthoringError):
        return KIND_BY_EXIT_CODE.get(exit_code_for(error), INTERNAL)
    if isinstance(error, (UsageError, ValueError)):
        return VALIDATION
    if isinstance(error, sqlite3.Error):
        return DATABASE
    return INTERNAL


def error_report(error: Exception) -> dict[str, Any]:
    kind = error_kind(error)
    report: dict[str, Any] = {"error": type(error).__name__, "message": str(error)}
    if isinstance(error, AuthoringError):
        report = problem_report(error)
    if isinstance(error, ValidationError):
        report["problems"] = [
            {"loc": ".".join(str(part) for part in detail["loc"]), "msg": detail["msg"]}
            for detail in error.errors()
        ]
    if isinstance(error, RenderLossError):
        report["rows"] = error.rows
    return {**report, "kind": kind, "next_step": NEXT_STEPS[kind]}
