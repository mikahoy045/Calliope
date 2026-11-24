from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Any

from calliope.authoring import audit
from calliope.config import settings
from calliope.db import get_db
from calliope.events.bus import EventBus, event_bus

EVENT_TYPE = "story.ready"
BATCH_LIMIT = 200
STOP_TIMEOUT_SEC = 5
TASK_NAME = "calliope-external-write-watcher"

logger = logging.getLogger("calliope.events.external_writes")


class ExternalWriteWatcher:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._last_entry_id = 0
        self._task: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        await self.skip_existing()
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._loop(self._stop), name=TASK_NAME)

    async def stop(self) -> None:
        if self._stop:
            self._stop.set()
        if self._task:
            await asyncio.wait([self._task], timeout=STOP_TIMEOUT_SEC)

    async def skip_existing(self) -> None:
        newest = await asyncio.to_thread(_read_entries, None, 1)
        self._last_entry_id = max((int(entry["id"]) for entry in newest), default=0)

    async def poll_once(self) -> int:
        entries = await asyncio.to_thread(_read_entries, self._last_entry_id, BATCH_LIMIT)
        if not entries:
            return 0
        self._last_entry_id = max(int(entry["id"]) for entry in entries)
        events = _events(entries)
        for event in events:
            await self._bus.publish(EVENT_TYPE, event)
        return len(events)

    async def _loop(self, stop: asyncio.Event) -> None:
        while not await _stopped_within(stop, settings.external_write_poll_sec):
            try:
                await self.poll_once()
            except sqlite3.Error:
                logger.warning("could not read external writes", exc_info=True)


async def _stopped_within(stop: asyncio.Event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return False
    return True


def _read_entries(since_id: int | None, limit: int) -> list[dict[str, Any]]:
    conn = get_db(settings.db_path)
    try:
        return audit.list_entries(conn, since_id=since_id, limit=limit)
    finally:
        conn.close()


def _events(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    oldest_first = sorted(entries, key=lambda entry: int(entry["id"]))
    by_project: dict[Any, list[dict[str, Any]]] = {}
    for entry in oldest_first:
        by_project.setdefault(entry.get("project_id"), []).append(entry)
    return [_event(project_id, writes) for project_id, writes in by_project.items()]


def _event(project_id: Any, writes: list[dict[str, Any]]) -> dict[str, Any]:
    latest = writes[-1]
    return {
        "project_id": project_id,
        "message": _message(latest, len(writes)),
        "source": latest.get("actor"),
        "entry_id": int(latest["id"]),
        "writes": len(writes),
    }


def _message(latest: dict[str, Any], count: int) -> str:
    detail = f"{latest.get('command')}"
    if latest.get("summary"):
        detail = f"{detail} ({latest['summary']})"
    if count > 1:
        return f"Written by {latest.get('actor')}: {count} writes, last {detail}"
    return f"Written by {latest.get('actor')}: {detail}"


external_write_watcher = ExternalWriteWatcher(event_bus)
