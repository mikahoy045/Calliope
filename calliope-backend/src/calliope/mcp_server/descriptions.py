from __future__ import annotations

from calliope.agent.idea_guard import LONG_IDEA_CHARS

READ_FALLBACK = "Read: runs `calliope-cli {group} {verb}` and returns its result."
WRITE_FALLBACK = (
    "Write: runs `calliope-cli {group} {verb}`. Call schema_show for the payload shape."
)

TOOL_DESCRIPTIONS: dict[tuple[str, str], str] = {
    ("project", "list"): (
        "List projects: id, title, genre, tone, status, ingest_mode and a short "
        "preview of the idea. Optional filters: status, ingest_mode."
    ),
    ("project", "show"): (
        "One project: its fields, the size of its source text, row counts per "
        "table and the continuity plan state. Set with_idea only when you need "
        "the whole source text; prefer project_source for long texts."
    ),
    ("project", "source"): (
        "Read a project's source text (the idea field) by character window with "
        "from_chars and to_chars, or search it with grep, a case-insensitive "
        "substring that returns matching lines with context_lines around them."
    ),
    ("project", "hash"): (
        "Content fingerprint of every writable table of a project. Call it just "
        "before reading rows you intend to change and pass that table's value as "
        "expect_hash on the write."
    ),
    ("project", "create"): (
        "Create a project and return its project_id. ingest_mode 'builtin', the "
        "default, keeps Calliope's own Draft storyline and Regenerate script "
        "buttons on the project; 'external' hides them."
    ),
    ("project", "set"): (
        "Change project fields: title, idea, genre, tone, target_duration, status. "
        "Only the fields you pass are written."
    ),
    ("story", "list"): (
        "List story beats in order: id, order_index, title, description. "
        "from_index and to_index select a range of positions."
    ),
    ("story", "get"): "Read one story beat by id.",
    ("story", "order"): (
        "Report gaps and duplicates in the beat positions without changing them. "
        "Check it before replacing a range of beats by position."
    ),
    ("story", "append"): (
        "Add story beats. payload is a list of beats; leave order_index out to add "
        "them at the end in the order given."
    ),
    ("story", "update"): (
        "Change one story beat's title, description or position. Only the fields "
        "you pass are written."
    ),
    ("story", "replace-range"): (
        "Replace the beats at positions from_index to to_index, both included, "
        "with the beats in payload. The replaced beats are removed."
    ),
    ("cast", "list"): (
        "List the cast: characters, locations and items, each with its fields and "
        "its image paths. Rows with a sheet_path, portrait_path or "
        "reference_image_path already have images made by the user."
    ),
    ("cast", "upsert"): (
        "Create or update characters, locations and items, matched by exact name. "
        "Characters take role, age, appearance and personality; locations and "
        "items take description. A field the kind does not have is rejected. "
        "Image prompts, sheets, portraits and reference images stay with the user "
        "in the web UI."
    ),
    ("cast", "update"): (
        "Change text fields of one character, location or item, found by id or "
        "exact name. Set kind to location or item for those; it defaults to "
        "character. Names cannot be changed here."
    ),
    ("script", "list"): (
        "List script scenes in order: heading, action, dialog, duration and "
        "location. from_index and to_index select a range of positions."
    ),
    ("script", "get"): "Read one scene by id with its clips and its character names.",
    ("script", "append"): (
        "Add script scenes at the end. payload is a list of scenes with heading, "
        "action, dialog, duration_sec, location_id and characters, the exact names "
        "of existing cast characters. Write dialog one line per speech as "
        "'SPEAKER: line', with an optional delivery cue such as "
        "'MIA (whispering): line'. Each new scene starts with one empty clip."
    ),
    ("script", "update"): (
        "Change one scene's heading, action, dialog, duration, position or "
        "location. Only the fields you pass are written. The scene keeps its clips "
        "and renders."
    ),
    ("script", "replace-range"): (
        "Replace the scenes at positions from_index to to_index, both included, "
        "with the scenes in payload. The replaced scenes are removed together with "
        "all their clips. Refused when a removed scene or clip holds a render or "
        "saved video settings, unless allow_render_loss is true."
    ),
    ("clips", "list"): (
        "List shot clips in render order with their scene's fields, for the whole "
        "project or for one scene_id. clip_path set means the clip is rendered."
    ),
    ("clips", "append"): (
        "Add shot clips to one scene. payload is a list of clips with description, "
        "shot_size, duration_sec and dialog_lines_covered, the 1-based numbers of "
        "the scene's dialog lines the clip performs. A new scene already has one "
        "empty clip: write the first shot onto it with clips_update, then append "
        "the rest. A continuity rule for one clip goes at the end of its "
        "description after a line that starts with [CARRY]."
    ),
    ("clips", "update"): (
        "Change one clip's description, shot_size, duration, position or "
        "dialog_lines_covered. Only the fields you pass are written. The clip keeps "
        "its render and video settings."
    ),
    ("clips", "replace-range"): (
        "Replace the clips at positions from_index to to_index of one scene, both "
        "included, with the clips in payload. The replaced clips are removed. "
        "Refused when a removed clip holds a render or saved video settings, unless "
        "allow_render_loss is true."
    ),
    ("context", "get"): (
        "Read the project's continuity notes: overview and requirements, and "
        "whether the derived shot plan is stale."
    ),
    ("context", "set"): (
        "Write the project's continuity notes. payload is one object with overview "
        "and requirements; each accepts a fixed set of keys, and its schema lists "
        "them with the length limit of a value."
    ),
    ("shots", "list"): (
        "Read the per-clip shot plan Calliope derives for rendering. Read only. "
        "Set carry to see each clip's [CARRY] rule."
    ),
    ("plan", "next"): (
        "Say what to write next for a project and why: beats, then cast, then "
        "script, then clips, then continuity notes. The answer 'render' means the "
        "text is complete and the user takes over in the web UI."
    ),
    ("log", "list"): (
        "List the writes made through these tools and the CLI, newest first, for "
        "one project or for all. command_filter takes a command such as "
        "'story append'."
    ),
    ("log", "show"): "Read one logged write with the rows as they were before it.",
    ("schema", "show"): (
        "Return the payload shape of a write as JSON Schema. Without arguments it "
        "lists the groups and verbs that take a payload."
    ),
    ("schema", "validate"): (
        "Check a payload against the shape of a write, named by group and verb, "
        "without writing anything."
    ),
}

ARGUMENT_DESCRIPTIONS: dict[str, str] = {
    "project": "Project id, or the exact project title.",
    "expect_hash": (
        "This table's fingerprint from project_hash, read just before this write. "
        "The write is refused with a drift error when the rows changed since then."
    ),
    "dry_run": "Check the write and report its result without writing anything.",
    "idea": (
        "The project's source text or synopsis. Multi-line text is accepted as it "
        f"is. Above {LONG_IDEA_CHARS} characters Calliope's own Draft storyline "
        "and Regenerate script buttons refuse to run on this project."
    ),
    "scene": "The scene's position in the script, counted from 1, or its scene id.",
    "entity_id": "The row id, or the exact name.",
    "dialog_lines_covered": (
        "The 1-based numbers of the scene's dialog lines this clip performs, as a "
        "list or separated by commas."
    ),
    "from_index": "First position, counted from 1.",
    "to_index": "Last position, included.",
}

PAYLOAD_ROWS = "The rows to write, one object per row."
PAYLOAD_DOCUMENT = "The document to write."
PAYLOAD_ANY = "The payload to check: a list of rows, or one object."
RENDER_LOSS = (
    "Allow this write to remove rows that hold renders or saved video settings. "
    "Set it to true only after the user agreed to lose exactly those rows."
)

INSTRUCTION_PARAGRAPHS = (
    "Calliope authoring tools. They write the text of a Calliope project (source text, "
    "story beats, cast, script scenes, shot clips, continuity notes) into the database "
    "the web UI reads. They never call Calliope's own LLM, never start a render and "
    "cannot delete a project. Calliope's own LLM features keep working beside them.",
    "Working order",
    "1. Find the project with project_list and project_show, or start one with project_create.",
    "2. plan_next says what to write next and why: beats, cast, script, clips, continuity notes.",
    "3. Every write tool carries its payload shape in its input schema. Unknown fields "
    "are rejected.",
    "4. Before changing rows that already exist, call project_hash, read the rows, then "
    "write with expect_hash set to that table's fingerprint.",
    '5. When plan_next answers "render", stop. The user reads the text in the web UI '
    "and presses Generate there.",
    "Rules",
    "- The user edits the same project in the web UI. A drift error means the rows "
    "changed since your read: read again and re-apply your change on top of what is "
    "there. Never force your earlier version over theirs.",
    "- Image prompts, reference photos, portraits, character sheets and every render "
    "belong to the user in the web UI. Do not change the appearance of a character or "
    "the description of a location that already has an image unless the user asks.",
    "- The replace_range tools remove rows, and on scenes they remove the scenes' clips "
    "too. Use the update tools for edits. A replace that would remove a render or "
    "saved video settings is refused; report the listed rows to the user and pass "
    "allow_render_loss only after they agree.",
    "- Keep a project's idea at or under {long_idea_chars} characters when the user "
    "still wants Calliope's own Draft storyline and Regenerate script buttons on that "
    "project. Put a long scenario into beats and scenes, not into the idea.",
    "- Read long texts in parts: project_source with from_chars and to_chars, "
    "story_list and script_list with from_index and to_index.",
    "- log_list and log_show show what these tools wrote and what the rows held before.",
)


def tool_description(group: str, verb: str, writes: bool) -> str:
    known = TOOL_DESCRIPTIONS.get((group, verb))
    if known:
        return known
    template = WRITE_FALLBACK if writes else READ_FALLBACK
    return template.format(group=group, verb=verb)


def argument_description(name: str, cli_help: str | None) -> str | None:
    return ARGUMENT_DESCRIPTIONS.get(name) or cli_help


def instructions() -> str:
    return "\n".join(INSTRUCTION_PARAGRAPHS).format(long_idea_chars=LONG_IDEA_CHARS)
