from __future__ import annotations

import asyncio
import sqlite3

import pytest

import calliope.config as config_module
from calliope.events import external_writes
from calliope.events.bus import EventBus
from calliope.events.external_writes import (
    EVENT_TYPE,
    ExternalWriteWatcher,
    external_write_watcher,
)

FAST_POLL_SEC = 0.05
WAIT_SEC = 5


@pytest.fixture
async def watched(cli_env):
    bus = EventBus()
    watcher = ExternalWriteWatcher(bus)
    await watcher.skip_existing()
    queue = await bus.subscribe()

    def append_beat(title, project=None, *extra):
        payload = cli_env["payload"](f"{title}.json", [{"title": title}])
        code, _, error = cli_env["json"](
            "story",
            "append",
            "--project",
            project or cli_env["project_id"],
            "--file",
            payload,
            *extra,
        )
        assert code == 0, error

    yield {**cli_env, "watcher": watcher, "queue": queue, "append_beat": append_beat}
    await watcher.stop()


async def test_write_made_outside_the_app_is_published(watched):
    watched["append_beat"]("Opening")

    published = await watched["watcher"].poll_once()

    event = watched["queue"].get_nowait()
    assert published == 1
    assert event["type"] == EVENT_TYPE
    assert event["data"]["project_id"] == watched["project_id"]
    assert event["data"]["source"] == "cli"
    assert "story append" in event["data"]["message"]


async def test_writes_made_before_the_watcher_started_are_not_replayed(watched):
    published = await watched["watcher"].poll_once()

    assert published == 0
    assert watched["queue"].empty()


async def test_write_is_published_only_once(watched):
    watched["append_beat"]("Opening")
    await watched["watcher"].poll_once()

    published_again = await watched["watcher"].poll_once()

    assert published_again == 0
    assert watched["queue"].qsize() == 1


async def test_burst_of_writes_to_one_project_becomes_one_event(watched):
    for title in ("One", "Two", "Three"):
        watched["append_beat"](title)

    published = await watched["watcher"].poll_once()

    event = watched["queue"].get_nowait()
    assert published == 1
    assert event["data"]["writes"] == 3
    assert "3 writes" in event["data"]["message"]


async def test_writes_to_two_projects_become_two_events(watched):
    _, created, _ = watched["json"]("project", "create", "--title", "Second")
    watched["append_beat"]("Opening")
    watched["append_beat"]("Elsewhere", created["project_id"])

    published = await watched["watcher"].poll_once()

    projects = {watched["queue"].get_nowait()["data"]["project_id"] for _ in range(published)}
    assert published == 2
    assert projects == {watched["project_id"], created["project_id"]}


async def test_dry_run_is_not_published(watched):
    watched["append_beat"]("Opening", None, "--dry-run")

    published = await watched["watcher"].poll_once()

    assert published == 0


async def test_running_watcher_publishes_on_its_own(watched, monkeypatch):
    monkeypatch.setattr(config_module.settings, "external_write_poll_sec", FAST_POLL_SEC)
    await watched["watcher"].start()

    watched["append_beat"]("Opening")
    event = await asyncio.wait_for(watched["queue"].get(), timeout=WAIT_SEC)

    assert watched["watcher"].is_running
    assert event["data"]["project_id"] == watched["project_id"]


async def test_stopped_watcher_is_not_running(watched, monkeypatch):
    monkeypatch.setattr(config_module.settings, "external_write_poll_sec", FAST_POLL_SEC)
    await watched["watcher"].start()

    await watched["watcher"].stop()

    assert not watched["watcher"].is_running


async def test_running_watcher_survives_a_database_error(watched, monkeypatch):
    monkeypatch.setattr(config_module.settings, "external_write_poll_sec", FAST_POLL_SEC)
    await watched["watcher"].start()
    read_entries = external_writes._read_entries
    failures = iter([sqlite3.OperationalError("database is locked")])

    def flaky(since_id, limit):
        for failure in failures:
            raise failure
        return read_entries(since_id, limit)

    monkeypatch.setattr(external_writes, "_read_entries", flaky)

    watched["append_beat"]("Opening")
    event = await asyncio.wait_for(watched["queue"].get(), timeout=WAIT_SEC)

    assert watched["watcher"].is_running
    assert event["data"]["project_id"] == watched["project_id"]


def test_backend_runs_the_watcher_while_it_serves(client):
    assert external_write_watcher.is_running


def test_backend_runs_the_watcher_again_after_a_restart(client):
    assert external_write_watcher.is_running


async def test_stop_before_start_does_nothing():
    watcher = ExternalWriteWatcher(EventBus())

    await watcher.stop()

    assert not watcher.is_running
