from __future__ import annotations

import json

import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from calliope.agent.idea_guard import LONG_IDEA_CHARS
from calliope.authoring.models import SHOT_SIZES
from calliope.cli import read_ops, write_ops
from calliope.cli.policy import is_forbidden_name
from calliope.mcp_server import build_server, descriptions
from calliope.mcp_server.surface import load_operations

CLI_OPERATIONS = {(group, verb) for group, verb, *_ in read_ops.READ_OPS} | {
    (group, verb) for group, verb, *_ in write_ops.WRITE_OPS
}
OPERATIONS = {operation.name: operation for operation in load_operations()}
RENDERED_CLIP = "assets/1/video/clip.mp4"


@pytest.fixture
def studio(cli_env):
    server = build_server()

    async def call(name, **arguments):
        async with Client(server) as client:
            result = await client.call_tool(name, arguments)
        return result.is_error, json.loads(result.content[0].text)

    return {**cli_env, "server": server, "call": call, "project": str(cli_env["project_id"])}


async def _scene_with_rendered_clip(studio):
    _, scenes = await studio["call"](
        "script_append",
        project=studio["project"],
        payload=[{"heading": "INT. HALL", "dialog": "MIA: Hello.\nBEN: Hi."}],
    )
    scene_id = scenes["scene_ids"][0]
    clip_id = (
        studio["conn"]
        .execute("SELECT id FROM clips WHERE scene_id = ?", (scene_id,))
        .fetchone()["id"]
    )
    studio["conn"].execute("UPDATE clips SET clip_path = ? WHERE id = ?", (RENDERED_CLIP, clip_id))
    return scene_id, clip_id


def test_every_cli_operation_is_exposed_exactly_once():
    exposed = [(operation.group, operation.verb) for operation in OPERATIONS.values()]

    assert set(exposed) == CLI_OPERATIONS
    assert len(exposed) == len(CLI_OPERATIONS)
    assert len(OPERATIONS) == len(CLI_OPERATIONS)


def test_no_tool_is_named_after_a_destructive_verb():
    offenders = [
        name for name in OPERATIONS if any(is_forbidden_name(part) for part in name.split("_"))
    ]

    assert offenders == []


def test_every_operation_has_a_written_description():
    assert set(descriptions.TOOL_DESCRIPTIONS) == CLI_OPERATIONS


def test_an_operation_without_a_written_description_still_gets_one():
    text = descriptions.tool_description("future", "verb", writes=True)

    assert "future verb" in text


def test_row_payload_schema_comes_from_the_input_model():
    schema = OPERATIONS["clips_append"].input_schema()
    row = schema["properties"]["payload"]["items"]

    assert schema["properties"]["payload"]["type"] == "array"
    assert row["properties"]["shot_size"]["anyOf"][0]["enum"] == list(SHOT_SIZES)
    assert "payload" in schema["required"]


def test_document_payload_is_one_object():
    payload = OPERATIONS["context_set"].input_schema()["properties"]["payload"]

    assert payload["type"] == "object"
    assert set(payload["properties"]) == {"overview", "requirements"}


def test_flag_driven_writes_take_no_payload():
    assert "payload" not in OPERATIONS["story_update"].argument_names
    assert "payload" not in OPERATIONS["project_set"].argument_names


def test_image_fields_are_not_arguments():
    cast_update = OPERATIONS["cast_update"].argument_names
    project_set = OPERATIONS["project_set"].argument_names

    assert not cast_update & {
        "consistency_prompt",
        "sheet_path",
        "portrait_path",
        "reference_image_path",
    }
    assert "cover_path" not in project_set


def test_project_is_required_where_the_command_needs_it():
    assert "project" in OPERATIONS["project_show"].required_names
    assert "project" in OPERATIONS["plan_next"].required_names
    assert "project" not in OPERATIONS["log_list"].required_names
    assert "project" not in OPERATIONS["project_list"].argument_names


def test_scene_is_an_argument_of_clip_writes_only():
    assert "scene" in OPERATIONS["clips_append"].required_names
    assert "scene" not in OPERATIONS["story_append"].argument_names
    assert "scene" not in OPERATIONS["script_replace_range"].argument_names


def test_only_writes_offer_a_dry_run():
    assert "dry_run" in OPERATIONS["story_append"].argument_names
    assert "dry_run" not in OPERATIONS["story_list"].argument_names


def test_only_row_removing_writes_offer_render_loss():
    offering = {name for name, operation in OPERATIONS.items() if operation.removes_rows}

    assert offering == {"story_replace_range", "script_replace_range", "clips_replace_range"}
    assert all("allow_render_loss" in OPERATIONS[name].argument_names for name in offering)
    assert "allow_render_loss" not in OPERATIONS["clips_update"].argument_names


def test_instructions_state_the_long_idea_limit():
    assert str(LONG_IDEA_CHARS) in descriptions.instructions()


async def test_listed_tools_match_the_operations(studio):
    async with Client(studio["server"]) as client:
        listing = await client.list_tools()

    assert {tool.name for tool in listing.tools} == set(OPERATIONS)
    assert all(tool.description for tool in listing.tools)
    assert all(tool.input_schema["additionalProperties"] is False for tool in listing.tools)


async def test_read_tools_are_marked_read_only(studio):
    async with Client(studio["server"]) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert tools["story_list"].annotations.read_only_hint is True
    assert tools["story_append"].annotations.read_only_hint is False
    assert tools["script_replace_range"].annotations.destructive_hint is True


async def test_write_is_recorded_with_the_mcp_actor(studio):
    failed, written = await studio["call"](
        "story_append", project=studio["project"], payload=[{"title": "Opening"}]
    )

    entry = (
        studio["conn"]
        .execute("SELECT actor FROM cli_audit WHERE command = 'story append'")
        .fetchone()
    )
    assert failed is False
    assert len(written["beat_ids"]) == 1
    assert entry["actor"] == "mcp"


async def test_stale_fingerprint_is_refused_as_drift(studio):
    await studio["call"]("story_append", project=studio["project"], payload=[{"title": "Opening"}])
    _, beats = await studio["call"]("story_list", project=studio["project"])

    failed, report = await studio["call"](
        "story_update",
        project=studio["project"],
        beat_id=beats[0]["id"],
        title="Changed",
        expect_hash="0000000000000000",
    )

    _, after = await studio["call"]("story_list", project=studio["project"])
    assert failed is True
    assert report["kind"] == "drift"
    assert report["report"]["table"] == "story_beats"
    assert after[0]["title"] == "Opening"


async def test_fresh_fingerprint_is_accepted(studio):
    await studio["call"]("story_append", project=studio["project"], payload=[{"title": "Opening"}])
    _, hashes = await studio["call"]("project_hash", project=studio["project"])
    _, beats = await studio["call"]("story_list", project=studio["project"])

    failed, _ = await studio["call"](
        "story_update",
        project=studio["project"],
        beat_id=beats[0]["id"],
        title="Changed",
        expect_hash=hashes["story_beats"],
    )

    _, after = await studio["call"]("story_list", project=studio["project"])
    assert failed is False
    assert after[0]["title"] == "Changed"


async def test_edit_made_in_the_web_ui_blocks_a_write_built_on_the_old_read(studio):
    await studio["call"]("story_append", project=studio["project"], payload=[{"title": "Opening"}])
    _, hashes = await studio["call"]("project_hash", project=studio["project"])
    _, beats = await studio["call"]("story_list", project=studio["project"])
    studio["conn"].execute(
        "UPDATE story_beats SET title = ? WHERE id = ?", ("Edited by hand", beats[0]["id"])
    )

    failed, report = await studio["call"](
        "story_update",
        project=studio["project"],
        beat_id=beats[0]["id"],
        title="Overwrite",
        expect_hash=hashes["story_beats"],
    )

    _, after = await studio["call"]("story_list", project=studio["project"])
    assert failed is True
    assert report["kind"] == "drift"
    assert after[0]["title"] == "Edited by hand"


async def test_unknown_argument_is_refused(studio):
    failed, report = await studio["call"]("story_list", project=studio["project"], nope=1)

    assert failed is True
    assert report["kind"] == "validation"
    assert "nope" in report["message"]


async def test_missing_required_argument_is_refused(studio):
    failed, report = await studio["call"]("story_append", project=studio["project"])

    assert failed is True
    assert report["kind"] == "validation"
    assert "payload" in report["message"]


async def test_wrongly_typed_argument_is_refused(studio):
    failed, report = await studio["call"]("story_list", project=studio["project"], from_index="x")

    assert failed is True
    assert report["kind"] == "validation"
    assert "from-index" in report["message"]


async def test_invalid_payload_row_is_reported_with_its_location(studio):
    failed, report = await studio["call"](
        "story_append", project=studio["project"], payload=[{"description": "no title"}]
    )

    assert failed is True
    assert report["kind"] == "validation"
    assert report["problems"][0]["problems"][0]["loc"] == "[0].title"


async def test_payload_sent_as_json_text_is_accepted(studio):
    failed, written = await studio["call"](
        "story_append", project=studio["project"], payload=json.dumps([{"title": "Opening"}])
    )

    assert failed is False
    assert len(written["beat_ids"]) == 1


async def test_payload_text_that_is_not_json_is_refused(studio):
    failed, report = await studio["call"](
        "story_append", project=studio["project"], payload="not json"
    )

    assert failed is True
    assert report["kind"] == "validation"


async def test_unknown_project_is_reported_as_not_found(studio):
    failed, report = await studio["call"]("story_list", project="999999")

    assert failed is True
    assert report["kind"] == "not_found"


async def test_dry_run_writes_nothing(studio):
    failed, _ = await studio["call"](
        "story_append", project=studio["project"], payload=[{"title": "Opening"}], dry_run=True
    )

    _, beats = await studio["call"]("story_list", project=studio["project"])
    assert failed is False
    assert beats == []


async def test_multiline_idea_starting_with_a_dash_round_trips(studio):
    idea = "- a list item first\nsecond line = with a sign\n"

    failed, _ = await studio["call"]("project_set", project=studio["project"], idea=idea)

    _, shown = await studio["call"]("project_show", project=studio["project"], with_idea=True)
    assert failed is False
    assert shown["idea"] == idea


async def test_empty_text_clears_a_field(studio):
    await studio["call"](
        "story_append",
        project=studio["project"],
        payload=[{"title": "Opening", "description": "A long night."}],
    )
    _, beats = await studio["call"]("story_list", project=studio["project"])

    await studio["call"](
        "story_update", project=studio["project"], beat_id=beats[0]["id"], description=""
    )

    _, after = await studio["call"]("story_list", project=studio["project"])
    assert after[0]["description"] == ""
    assert after[0]["title"] == "Opening"


async def test_number_list_is_passed_as_dialog_lines(studio):
    _, clip_id = await _scene_with_rendered_clip(studio)

    failed, _ = await studio["call"](
        "clips_update", project=studio["project"], clip_id=clip_id, dialog_lines_covered=[2, 1]
    )

    _, clips = await studio["call"]("clips_list", project=studio["project"])
    assert failed is False
    assert clips[0]["dialog_lines_covered"] == [1, 2]


async def test_clip_update_keeps_the_render(studio):
    _, clip_id = await _scene_with_rendered_clip(studio)

    failed, _ = await studio["call"](
        "clips_update", project=studio["project"], clip_id=clip_id, description="Wide on the hall."
    )

    _, clips = await studio["call"]("clips_list", project=studio["project"])
    assert failed is False
    assert clips[0]["clip_path"] == RENDERED_CLIP
    assert clips[0]["description"] == "Wide on the hall."


async def test_clip_replace_is_refused_when_a_clip_holds_a_render(studio):
    _, clip_id = await _scene_with_rendered_clip(studio)

    failed, report = await studio["call"](
        "clips_replace_range",
        project=studio["project"],
        scene="1",
        from_index=1,
        to_index=1,
        payload=[{"description": "New shot."}],
    )

    _, clips = await studio["call"]("clips_list", project=studio["project"])
    assert failed is True
    assert report["kind"] == "render_loss"
    assert report["rows"]["removed"] == [{"id": clip_id, "order_index": 1, "holds": ["clip_path"]}]
    assert [clip["id"] for clip in clips] == [clip_id]


async def test_scene_replace_is_refused_when_one_of_its_clips_holds_a_render(studio):
    scene_id, clip_id = await _scene_with_rendered_clip(studio)

    failed, report = await studio["call"](
        "script_replace_range",
        project=studio["project"],
        from_index=1,
        to_index=1,
        payload=[{"heading": "EXT. YARD"}],
    )

    _, scenes = await studio["call"]("script_list", project=studio["project"])
    assert failed is True
    assert report["kind"] == "render_loss"
    assert report["rows"]["removed_clips"][0]["id"] == clip_id
    assert [scene["id"] for scene in scenes] == [scene_id]


async def test_refused_replace_leaves_no_log_entry(studio):
    await _scene_with_rendered_clip(studio)

    await studio["call"](
        "clips_replace_range",
        project=studio["project"],
        scene="1",
        from_index=1,
        to_index=1,
        payload=[{"description": "New shot."}],
    )

    entries = (
        studio["conn"]
        .execute("SELECT COUNT(*) AS n FROM cli_audit WHERE command = 'clips replace-range'")
        .fetchone()
    )
    assert entries["n"] == 0


async def test_replace_goes_through_once_render_loss_is_allowed(studio):
    _, clip_id = await _scene_with_rendered_clip(studio)

    failed, _ = await studio["call"](
        "clips_replace_range",
        project=studio["project"],
        scene="1",
        from_index=1,
        to_index=1,
        payload=[{"description": "New shot."}],
        allow_render_loss=True,
    )

    _, clips = await studio["call"]("clips_list", project=studio["project"])
    assert failed is False
    assert [clip["description"] for clip in clips] == ["New shot."]
    assert clip_id not in [clip["id"] for clip in clips]


async def test_replace_of_unrendered_rows_goes_through(studio):
    await studio["call"](
        "script_append", project=studio["project"], payload=[{"heading": "INT. HALL"}]
    )

    failed, _ = await studio["call"](
        "clips_replace_range",
        project=studio["project"],
        scene="1",
        from_index=1,
        to_index=1,
        payload=[{"description": "First shot."}, {"description": "Second shot."}],
    )

    _, clips = await studio["call"]("clips_list", project=studio["project"])
    assert failed is False
    assert [clip["description"] for clip in clips] == ["First shot.", "Second shot."]


async def test_image_prompt_cannot_be_written(studio):
    await studio["call"](
        "cast_upsert", project=studio["project"], payload=[{"name": "Mia", "appearance": "Tall."}]
    )

    failed, report = await studio["call"](
        "cast_update", project=studio["project"], entity_id="Mia", consistency_prompt="A sheet."
    )

    assert failed is True
    assert report["kind"] == "validation"


async def test_gap_in_the_stored_scene_order_is_reported_as_ordering(studio):
    _, clip_id = await _scene_with_rendered_clip(studio)
    studio["conn"].execute("UPDATE scenes SET order_index = order_index + 1")

    failed, report = await studio["call"](
        "clips_update", project=studio["project"], clip_id=clip_id, description="Wide."
    )

    assert failed is True
    assert report["kind"] == "ordering"
    assert "script_update" in report["next_step"]


async def test_moving_a_scene_repairs_a_gap_in_the_scene_order(studio):
    scene_id, clip_id = await _scene_with_rendered_clip(studio)
    studio["conn"].execute("UPDATE scenes SET order_index = order_index + 1")

    await studio["call"](
        "script_update", project=studio["project"], scene_id=scene_id, order_index=1
    )
    failed, _ = await studio["call"](
        "clips_update", project=studio["project"], clip_id=clip_id, description="Wide."
    )

    _, clips = await studio["call"]("clips_list", project=studio["project"])
    assert failed is False
    assert clips[0]["description"] == "Wide."
    assert clips[0]["clip_path"] == RENDERED_CLIP


async def test_unknown_tool_is_a_protocol_error(studio):
    async with Client(studio["server"]) as client:
        with pytest.raises(MCPError):
            await client.call_tool("project_erase", {})
