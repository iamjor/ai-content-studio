"""Bounded, account-scoped workspace operations for the MCP endpoint."""

import json
import secrets
import time

import server

MAX_TEXT = 20_000
MAX_SHOTS = 200
MAX_GATES = 100
BIBLE_LIMITS = {
    "logline": 1_000, "premise": MAX_TEXT, "seasonArc": MAX_TEXT,
    "worldRules": MAX_TEXT, "toneStyle": MAX_TEXT, "audience": 1_000,
    "language": 100, "aspectRatio": 40, "productionConstraints": MAX_TEXT,
}
CONTINUITY_LIMITS = {
    "mustKeep": 5_000, "mustAvoid": 5_000,
    "wardrobeVariants": 5_000, "voice": 5_000,
}
SHOT_LIMITS = {
    "timeRange": 40, "visualBeat": 5_000, "cameraAction": 5_000,
    "dialogue": 10_000, "audioNotes": 5_000, "promptId": 120,
    "imagePrompt": MAX_TEXT, "videoPrompt": MAX_TEXT,
    "referenceAssets": 5_000, "modelSettings": 5_000, "outputLink": 1_000,
}
SHOT_STATUSES = {"Planned", "In progress", "Ready for review", "Approved"}


class ServiceError(Exception):
    """Represent a safe MCP error with a stable code and optional details."""

    def __init__(self, code, message, details=None):
        """Store fields that may be returned to the authenticated caller."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def as_result(self):
        """Serialize the error without internal database or filesystem details."""
        return {"ok": False, "error": self.code, "message": self.message, **self.details}


def text(value, field, limit, required=False):
    """Validate bounded text without silently truncating caller content."""
    if not isinstance(value, str) or len(value) > limit:
        raise ServiceError("invalid_input", f"{field} must be text up to {limit} characters.")
    if required and not value.strip():
        raise ServiceError("invalid_input", f"{field} is required.")
    return value


def load(database, user_id):
    """Load and normalize one user's workspace within the caller's transaction."""
    row = database.execute(
        "SELECT revision, data FROM workspaces WHERE user_id=?", (user_id,)
    ).fetchone()
    if not row:
        return 0, {"projects": [], "activeId": ""}
    try:
        data = json.loads(row["data"])
    except json.JSONDecodeError as error:
        raise ServiceError("workspace_unavailable", "Workspace data could not be read.") from error
    data, _ = server.normalize_workspace_data(data)
    return row["revision"], data


def project(data, project_id):
    """Resolve a project by stable ID inside one already scoped workspace."""
    for item in data.get("projects", []):
        if isinstance(item, dict) and item.get("id") == project_id:
            return item
    raise ServiceError("not_found", "Project not found.")


def record(records, record_id, label):
    """Resolve a nested record by stable ID."""
    for item in records:
        if isinstance(item, dict) and item.get("id") == record_id:
            return item
    raise ServiceError("not_found", f"{label} not found.")


def workspace(user_id):
    """Return one user's current normalized workspace and revision."""
    with server.connect() as database:
        return load(database, user_id)


def mutate_workspace(user_id, expected_revision, callback):
    """Apply one optimistic mutation and return its exact new revision."""
    if type(expected_revision) is not int or expected_revision < 0:
        raise ServiceError("invalid_input", "expected_revision must be a non-negative integer.")
    with server.connect() as database:
        database.execute("BEGIN IMMEDIATE")
        revision, data = load(database, user_id)
        if revision != expected_revision:
            raise ServiceError(
                "revision_conflict", "Workspace changed. Read it again before updating.",
                {"currentRevision": revision},
            )
        result = callback(database, data)
        if revision == 0:
            saved = database.execute(
                "INSERT OR IGNORE INTO workspaces (user_id, revision, data) VALUES (?, 1, ?)",
                (user_id, json.dumps(data)),
            )
        else:
            saved = database.execute(
                """
                UPDATE workspaces SET revision=revision+1, data=?
                WHERE user_id=? AND revision=?
                """,
                (json.dumps(data), user_id, revision),
            )
        if saved.rowcount != 1:
            raise ServiceError("revision_conflict", "Workspace changed. Read it again.")
    return {"ok": True, "revision": revision + 1, **result}


def get_workspace_summary(user_id):
    """Summarize only the authenticated user's workspace."""
    revision, data = workspace(user_id)
    projects = [item for item in data.get("projects", []) if isinstance(item, dict)]
    return {
        "revision": revision, "activeProjectId": data.get("activeId", ""),
        "counts": {
            "projects": len(projects),
            "episodes": sum(len(item.get("episodes", [])) for item in projects),
            "characters": sum(len(item.get("characters", [])) for item in projects),
            "prompts": sum(len(item.get("prompts", [])) for item in projects),
            "gates": sum(len(item.get("gates", [])) for item in projects),
            "shots": sum(
                len(episode.get("shots", []))
                for item in projects for episode in item.get("episodes", [])
                if isinstance(episode, dict)
            ),
        },
    }


def list_projects(user_id, include_archived=False):
    """List project metadata without embedding nested planning records."""
    revision, data = workspace(user_id)
    fields = ("id", "title", "genre", "description", "stage", "archived")
    return {
        "revision": revision,
        "projects": [
            {key: item.get(key, "") for key in fields}
            for item in data.get("projects", [])
            if isinstance(item, dict) and (include_archived or not item.get("archived"))
        ],
    }


def get_project(user_id, project_id):
    """Return project metadata plus stable nested record IDs."""
    revision, data = workspace(user_id)
    item = project(data, project_id)
    value = {
        key: item.get(key, "")
        for key in ("id", "title", "genre", "description", "stage", "archived")
    }
    for output, source in (
        ("episodeIds", "episodes"), ("characterIds", "characters"),
        ("promptIds", "prompts"), ("gateIds", "gates"),
    ):
        value[output] = [
            child.get("id") for child in item.get(source, []) if isinstance(child, dict)
        ]
    return {"revision": revision, "project": value}


def get_project_bible(user_id, project_id):
    """Return one caller-owned project Bible."""
    revision, data = workspace(user_id)
    return {
        "revision": revision, "projectId": project_id,
        "bible": project(data, project_id).get("bible", {}),
    }


def list_episodes(user_id, project_id, include_archived=False):
    """List episodes in a caller-owned project."""
    revision, data = workspace(user_id)
    fields = ("id", "title", "hook", "synopsis", "status", "duration", "archived")
    episodes = project(data, project_id).get("episodes", [])
    return {
        "revision": revision, "projectId": project_id,
        "episodes": [
            {key: item.get(key, "") for key in fields}
            for item in episodes
            if isinstance(item, dict) and (include_archived or not item.get("archived"))
        ],
    }


def get_episode(user_id, project_id, episode_id):
    """Return one episode including script, hook, planning, and shot snapshots."""
    revision, data = workspace(user_id)
    item = record(project(data, project_id).get("episodes", []), episode_id, "Episode")
    return {"revision": revision, "projectId": project_id, "episode": item}


def list_characters(user_id, project_id, include_archived=False):
    """List characters while exposing no image bytes, URLs, or storage paths."""
    revision, data = workspace(user_id)
    with server.connect() as database:
        image_ids = {
            row["character_id"] for row in database.execute(
                "SELECT character_id FROM character_images WHERE user_id=?", (user_id,)
            ).fetchall()
        }
    values = []
    for item in project(data, project_id).get("characters", []):
        if not isinstance(item, dict) or (item.get("archived") and not include_archived):
            continue
        value = dict(item)
        value.pop("hasImage", None)
        value["hasApprovedPrivateImage"] = item.get("id") in image_ids
        values.append(value)
    return {"revision": revision, "projectId": project_id, "characters": values}


def get_character(user_id, project_id, character_id):
    """Return one character and only a boolean for its browser-only private image."""
    result = list_characters(user_id, project_id, include_archived=True)
    return {
        "revision": result["revision"], "projectId": project_id,
        "character": record(result["characters"], character_id, "Character"),
    }


def list_prompts(user_id, project_id, include_archived=False):
    """List reusable prompts for one caller-owned project."""
    revision, data = workspace(user_id)
    prompts = project(data, project_id).get("prompts", [])
    return {
        "revision": revision, "projectId": project_id,
        "prompts": [
            item for item in prompts
            if isinstance(item, dict) and (include_archived or not item.get("archived"))
        ],
    }


def list_production_gates(user_id, project_id):
    """List manual gates without inferring approval from other record text."""
    revision, data = workspace(user_id)
    return {
        "revision": revision, "projectId": project_id,
        "gates": project(data, project_id).get("gates", []),
    }


def update_project_bible(user_id, project_id, expected_revision, changes):
    """Partially update Bible fields while preserving every omitted field."""
    if not isinstance(changes, dict) or not changes or set(changes) - set(BIBLE_LIMITS):
        raise ServiceError("invalid_input", "Supply only supported Bible fields.")
    clean = {key: text(value, key, BIBLE_LIMITS[key]) for key, value in changes.items()}

    def apply(database, data):
        project(data, project_id).setdefault("bible", {}).update(clean)
        return {"changed": [{"type": "projectBible", "id": project_id, "fields": sorted(clean)}]}

    return mutate_workspace(user_id, expected_revision, apply)


def update_episode_planning(
    user_id, project_id, episode_id, expected_revision, synopsis=None, beats=None
):
    """Update synopsis and beats while preserving hook, script, and omitted fields."""
    changes = {}
    if synopsis is not None:
        changes["synopsis"] = text(synopsis, "synopsis", MAX_TEXT)
    if beats is not None:
        changes["beats"] = text(beats, "beats", MAX_TEXT)
    if not changes:
        raise ServiceError("invalid_input", "Supply synopsis or beats.")

    def apply(database, data):
        item = record(project(data, project_id).get("episodes", []), episode_id, "Episode")
        item.update(changes)
        return {"changed": [{"type": "episode", "id": episode_id, "fields": sorted(changes)}]}

    return mutate_workspace(user_id, expected_revision, apply)


def clean_shot(value):
    """Validate one complete shot and preserve its final prompt snapshots."""
    allowed = {"id", "status", *SHOT_LIMITS}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ServiceError("invalid_input", "A shot contains unsupported fields.")
    shot_id = value.get("id") or "shot-" + secrets.token_hex(12)
    if not server.IDENTIFIER_PATTERN.fullmatch(shot_id):
        raise ServiceError("invalid_input", "Shot ID is invalid.")
    result = {"id": shot_id}
    for key, limit in SHOT_LIMITS.items():
        result[key] = text(value.get(key, ""), key, limit)
    result["status"] = value.get("status", "Planned")
    if result["status"] not in SHOT_STATUSES:
        raise ServiceError("invalid_input", "Shot status is invalid.")
    return result


def replace_episode_shots(user_id, project_id, episode_id, expected_revision, shots):
    """Replace only one episode's ordered shots after validating the full payload."""
    if not isinstance(shots, list) or len(shots) > MAX_SHOTS:
        raise ServiceError("invalid_input", f"shots must contain at most {MAX_SHOTS} items.")
    clean = [clean_shot(item) for item in shots]
    ids = [item["id"] for item in clean]
    if len(ids) != len(set(ids)):
        raise ServiceError("invalid_input", "Shot IDs must be unique.")

    def apply(database, data):
        owner = project(data, project_id)
        prompt_ids = {
            item.get("id") for item in owner.get("prompts", []) if isinstance(item, dict)
        }
        if any(item["promptId"] and item["promptId"] not in prompt_ids for item in clean):
            raise ServiceError("invalid_input", "A linked prompt does not belong to this project.")
        episode = record(owner.get("episodes", []), episode_id, "Episode")
        episode["shots"] = clean
        return {"changed": [{"type": "episodeShots", "id": episode_id, "shotIds": ids}]}

    return mutate_workspace(user_id, expected_revision, apply)


def update_character_planning(
    user_id, project_id, character_id, expected_revision,
    reference_requirements=None, continuity=None,
):
    """Partially update character reference requirements and continuity locks."""
    reference = (
        None if reference_requirements is None
        else text(reference_requirements, "reference_requirements", 10_000)
    )
    if continuity is not None and (
        not isinstance(continuity, dict) or set(continuity) - set(CONTINUITY_LIMITS)
    ):
        raise ServiceError("invalid_input", "Continuity contains unsupported fields.")
    clean = {
        key: text(value, key, CONTINUITY_LIMITS[key])
        for key, value in (continuity or {}).items()
    }
    if reference is None and not clean:
        raise ServiceError("invalid_input", "Supply reference requirements or continuity.")

    def apply(database, data):
        item = record(
            project(data, project_id).get("characters", []), character_id, "Character"
        )
        fields = []
        if reference is not None:
            item["referenceRequirements"] = reference
            fields.append("referenceRequirements")
        item.setdefault("continuity", {}).update(clean)
        fields.extend("continuity." + key for key in clean)
        return {"changed": [{"type": "character", "id": character_id, "fields": fields}]}

    return mutate_workspace(user_id, expected_revision, apply)


def upsert_project_prompt(
    user_id, project_id, expected_revision, name, category, body,
    prompt_id=None, purpose="", model_settings="",
):
    """Create or update a prompt while leaving shot prompt snapshots unchanged."""
    values = {
        "name": text(name, "name", 120, True).strip(),
        "category": text(category, "category", 80, True).strip(),
        "purpose": text(purpose, "purpose", 300),
        "body": text(body, "body", MAX_TEXT, True),
        "modelSettings": text(model_settings, "model_settings", 5_000),
    }
    if prompt_id is not None and not server.IDENTIFIER_PATTERN.fullmatch(prompt_id):
        raise ServiceError("invalid_input", "Prompt ID is invalid.")

    def apply(database, data):
        prompts = project(data, project_id).setdefault("prompts", [])
        target = record(prompts, prompt_id, "Prompt") if prompt_id else None
        record_id = prompt_id or "prompt-" + secrets.token_hex(12)
        if target is None:
            target = {"id": record_id, "archived": False}
            prompts.append(target)
        target.update(values)
        target["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return {"changed": [{"type": "prompt", "id": record_id, "action": "updated" if prompt_id else "created"}]}

    return mutate_workspace(user_id, expected_revision, apply)


def update_production_gates(user_id, project_id, expected_revision, gates):
    """Create or update gates without deleting omitted gates."""
    if not isinstance(gates, list) or not 1 <= len(gates) <= MAX_GATES:
        raise ServiceError("invalid_input", f"gates must contain 1 to {MAX_GATES} items.")
    clean = []
    for value in gates:
        if not isinstance(value, dict) or set(value) - {"id", "name", "done"}:
            raise ServiceError("invalid_input", "A gate contains unsupported fields.")
        if value.get("id") and not server.IDENTIFIER_PATTERN.fullmatch(value["id"]):
            raise ServiceError("invalid_input", "Gate ID is invalid.")
        if type(value.get("done", False)) is not bool:
            raise ServiceError("invalid_input", "Gate done must be true or false.")
        clean.append({
            "id": value.get("id"),
            "name": text(value.get("name", ""), "gate name", 160, True).strip(),
            "done": value.get("done", False),
        })

    def apply(database, data):
        gates_list = project(data, project_id).setdefault("gates", [])
        existing = {
            item.get("id"): item for item in gates_list if isinstance(item, dict)
        }
        changed = []
        for value in clean:
            gate_id = value["id"] or "gate-" + secrets.token_hex(12)
            if value["id"] and gate_id not in existing:
                raise ServiceError("not_found", "Gate not found.")
            target = existing.get(gate_id)
            if target is None:
                target = {"id": gate_id}
                gates_list.append(target)
            target.update({"name": value["name"], "done": value["done"]})
            changed.append(gate_id)
        return {"changed": [{"type": "productionGates", "ids": changed}]}

    return mutate_workspace(user_id, expected_revision, apply)


def set_archive_state(
    user_id, project_id, record_type, record_id, expected_revision, archived
):
    """Archive or restore one project, episode, character, or prompt."""
    collections = {"episode": "episodes", "character": "characters", "prompt": "prompts"}
    if record_type not in {"project", *collections}:
        raise ServiceError("invalid_input", "Unsupported archive record type.")

    def apply(database, data):
        owner = project(data, project_id)
        target = owner if record_type == "project" else record(
            owner.get(collections[record_type], []), record_id, record_type.title()
        )
        target["archived"] = archived
        return {"changed": [{"type": record_type, "id": target.get("id"), "archived": archived}]}

    return mutate_workspace(user_id, expected_revision, apply)



def _remove_private_images(database, user_id, character_ids):
    """Delete scoped image metadata and return opaque storage IDs for cleanup."""
    character_ids = set(character_ids)
    rows = database.execute(
        "SELECT storage_id, character_id FROM character_images WHERE user_id=?",
        (user_id,),
    ).fetchall()
    selected = [row for row in rows if row["character_id"] in character_ids]
    for row in selected:
        database.execute(
            "DELETE FROM character_images WHERE storage_id=? AND user_id=?",
            (row["storage_id"], user_id),
        )
    return [row["storage_id"] for row in selected]


def _finish_image_cleanup(user_id, result):
    """Remove image files after commit without exposing their private storage names."""
    storage_ids = result.pop("_storageIds", [])
    pending = 0
    for storage_id in storage_ids:
        try:
            (server.image_root() / str(user_id) / storage_id).unlink(missing_ok=True)
        except OSError:
            pending += 1
    result["receipt"]["privateImagesDeleted"] = len(storage_ids) - pending
    if pending:
        result["receipt"]["privateImageFilesPendingCleanup"] = pending
    return result


def _confirmed(actual, confirmation, label):
    """Require an exact, bounded confirmation value for permanent deletion."""
    text(confirmation, "confirmation", 200, True)
    if confirmation != actual:
        raise ServiceError(
            "confirmation_mismatch", f"Confirmation must exactly match the {label}."
        )


def delete_project(user_id, project_id, expected_revision, confirmation):
    """Permanently delete one project and its owned records and private images."""
    def apply(database, data):
        target = project(data, project_id)
        _confirmed(target.get("title", ""), confirmation, "project title")
        episodes = [item for item in target.get("episodes", []) if isinstance(item, dict)]
        characters = [item for item in target.get("characters", []) if isinstance(item, dict)]
        other_character_ids = {
            item.get("id")
            for owner in data.get("projects", [])
            if isinstance(owner, dict) and owner is not target
            for item in owner.get("characters", [])
            if isinstance(item, dict)
        }
        storage_ids = _remove_private_images(
            database, user_id,
            [
                item.get("id") for item in characters
                if item.get("id") not in other_character_ids
            ],
        )
        data["projects"].remove(target)
        if data.get("activeId") == project_id:
            data["activeId"] = next(
                (
                    item.get("id", "") for item in data["projects"]
                    if isinstance(item, dict) and not item.get("archived")
                ),
                "",
            )
        return {
            "changed": [{"type": "project", "id": project_id, "deleted": True}],
            "receipt": {
                "type": "project", "id": project_id, "title": target.get("title", ""),
                "episodesDeleted": len(episodes),
                "charactersDeleted": len(characters),
                "promptsDeleted": len(target.get("prompts", [])),
                "shotsDeleted": sum(len(item.get("shots", [])) for item in episodes),
                "gatesDeleted": len(target.get("gates", [])),
            },
            "_storageIds": storage_ids,
        }

    return _finish_image_cleanup(
        user_id, mutate_workspace(user_id, expected_revision, apply)
    )


def delete_episode(user_id, project_id, episode_id, expected_revision, confirmation):
    """Permanently delete one episode and only its owned shot plan."""
    def apply(database, data):
        episodes = project(data, project_id).get("episodes", [])
        target = record(episodes, episode_id, "Episode")
        _confirmed(target.get("title", ""), confirmation, "episode title")
        shot_count = len(target.get("shots", []))
        episodes.remove(target)
        return {
            "changed": [{"type": "episode", "id": episode_id, "deleted": True}],
            "receipt": {
                "type": "episode", "id": episode_id,
                "title": target.get("title", ""), "shotsDeleted": shot_count,
            },
        }

    return mutate_workspace(user_id, expected_revision, apply)


def delete_character(user_id, project_id, character_id, expected_revision, confirmation):
    """Permanently delete one character and its account-scoped private image."""
    def apply(database, data):
        characters = project(data, project_id).get("characters", [])
        target = record(characters, character_id, "Character")
        _confirmed(target.get("name", ""), confirmation, "character name")
        shared_elsewhere = any(
            item.get("id") == character_id
            for owner in data.get("projects", [])
            if isinstance(owner, dict)
            for item in owner.get("characters", [])
            if isinstance(item, dict) and item is not target
        )
        storage_ids = _remove_private_images(
            database, user_id, [] if shared_elsewhere else [character_id]
        )
        characters.remove(target)
        return {
            "changed": [{"type": "character", "id": character_id, "deleted": True}],
            "receipt": {
                "type": "character", "id": character_id,
                "name": target.get("name", ""),
            },
            "_storageIds": storage_ids,
        }

    return _finish_image_cleanup(
        user_id, mutate_workspace(user_id, expected_revision, apply)
    )


def delete_project_prompt(user_id, project_id, prompt_id, expected_revision, confirmation):
    """Delete one reusable prompt while preserving shot prompt snapshots."""
    def apply(database, data):
        prompts = project(data, project_id).get("prompts", [])
        target = record(prompts, prompt_id, "Prompt")
        _confirmed(target.get("name", ""), confirmation, "prompt name")
        prompts.remove(target)
        return {
            "changed": [{"type": "prompt", "id": prompt_id, "deleted": True}],
            "receipt": {
                "type": "prompt", "id": prompt_id,
                "name": target.get("name", ""), "shotSnapshotsPreserved": True,
            },
        }

    return mutate_workspace(user_id, expected_revision, apply)


def delete_episode_shot(
    user_id, project_id, episode_id, shot_id, expected_revision, confirmation
):
    """Delete one shot, using its stable ID as confirmation because shots lack names."""
    def apply(database, data):
        episode = record(
            project(data, project_id).get("episodes", []), episode_id, "Episode"
        )
        shots = episode.get("shots", [])
        target = record(shots, shot_id, "Shot")
        _confirmed(shot_id, confirmation, "shot ID")
        shots.remove(target)
        return {
            "changed": [{"type": "shot", "id": shot_id, "deleted": True}],
            "receipt": {
                "type": "shot", "id": shot_id, "episodeId": episode_id,
            },
        }

    return mutate_workspace(user_id, expected_revision, apply)


def delete_production_gate(
    user_id, project_id, gate_id, expected_revision, confirmation
):
    """Permanently delete one named production gate."""
    def apply(database, data):
        gates = project(data, project_id).get("gates", [])
        target = record(gates, gate_id, "Production gate")
        _confirmed(target.get("name", ""), confirmation, "gate name")
        gates.remove(target)
        return {
            "changed": [{"type": "productionGate", "id": gate_id, "deleted": True}],
            "receipt": {
                "type": "productionGate", "id": gate_id,
                "name": target.get("name", ""),
            },
        }

    return mutate_workspace(user_id, expected_revision, apply)
