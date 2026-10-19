"""Official-SDK MCP server for account-scoped AI Content Studio planning data."""

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import Field

import mcp_service
import server

READ = {
    "readOnlyHint": True, "destructiveHint": False,
    "idempotentHint": True, "openWorldHint": False,
}
WRITE = {
    "readOnlyHint": False, "destructiveHint": False,
    "idempotentHint": False, "openWorldHint": False,
}
ARCHIVE = {
    "readOnlyHint": False, "destructiveHint": True,
    "idempotentHint": True, "openWorldHint": False,
}
RESTORE = {
    "readOnlyHint": False, "destructiveHint": False,
    "idempotentHint": True, "openWorldHint": False,
}
DELETE = {
    "readOnlyHint": False, "destructiveHint": True,
    "idempotentHint": False, "openWorldHint": False,
}
Identifier = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")]
Revision = Annotated[int, Field(ge=0)]
BoundedText = Annotated[str, Field(max_length=20_000)]
Confirmation = Annotated[str, Field(min_length=1, max_length=200)]


class DatabaseTokenVerifier:
    """Validate opaque bearer tokens against hashed, revocable SQLite records."""

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return SDK authorization context for one active account token."""
        identity = server.resolve_access_token(token, touch=True)
        if not identity:
            return None
        return AccessToken(
            token=token,
            client_id=identity["client_id"],
            scopes=identity["scopes"].split(),
            expires_at=identity["expires_at"],
            resource=server.PUBLIC_BASE_URL + "/mcp",
            subject=str(identity["user_id"]),
        )


mcp = MCPServer(
    "AI Content Studio",
    instructions=(
        "Read and update only the authenticated user's content-planning records. "
        "Use the returned workspace revision for each write."
    ),
    token_verifier=DatabaseTokenVerifier(),
    auth=AuthSettings(
        issuer_url=server.PUBLIC_BASE_URL,
        resource_server_url=server.PUBLIC_BASE_URL + "/mcp",
        required_scopes=[],
        validate_token_resource=True,
    ),
)


def caller(scope: str) -> int:
    """Return the authenticated account ID after enforcing one narrow scope."""
    access = get_access_token()
    if not access or scope not in access.scopes or not access.subject:
        raise PermissionError(f"{scope} scope is required.")
    try:
        return int(access.subject)
    except ValueError as error:
        raise PermissionError("The access-token subject is invalid.") from error


def call(scope: str, operation, *args, **kwargs) -> dict[str, Any]:
    """Run one service operation and convert expected failures to safe results."""
    try:
        return operation(caller(scope), *args, **kwargs)
    except mcp_service.ServiceError as error:
        return error.as_result()
    except PermissionError as error:
        return {"ok": False, "error": "insufficient_scope", "message": str(error)}


@mcp.tool(annotations=READ)
def get_workspace_summary() -> dict[str, Any]:
    """Return the caller's workspace revision, active project ID, and record counts."""
    return call("aics.read", mcp_service.get_workspace_summary)


@mcp.tool(annotations=READ)
def list_projects(include_archived: bool = False) -> dict[str, Any]:
    """List caller-owned projects, optionally including archived projects."""
    return call("aics.read", mcp_service.list_projects, include_archived)


@mcp.tool(annotations=READ)
def get_project(project_id: Identifier) -> dict[str, Any]:
    """Get one caller-owned project's metadata and nested stable IDs."""
    return call("aics.read", mcp_service.get_project, project_id)


@mcp.tool(annotations=READ)
def get_project_bible(project_id: Identifier) -> dict[str, Any]:
    """Get all dedicated Bible fields for one caller-owned project."""
    return call("aics.read", mcp_service.get_project_bible, project_id)


@mcp.tool(annotations=READ)
def list_episodes(
    project_id: Identifier, include_archived: bool = False
) -> dict[str, Any]:
    """List episodes in one caller-owned project."""
    return call(
        "aics.read", mcp_service.list_episodes, project_id, include_archived
    )


@mcp.tool(annotations=READ)
def get_episode(project_id: Identifier, episode_id: Identifier) -> dict[str, Any]:
    """Get one episode including hook, script, synopsis, beats, and shot snapshots."""
    return call("aics.read", mcp_service.get_episode, project_id, episode_id)


@mcp.tool(annotations=READ)
def list_characters(
    project_id: Identifier, include_archived: bool = False
) -> dict[str, Any]:
    """List characters without returning private image bytes, URLs, or paths."""
    return call(
        "aics.read", mcp_service.list_characters, project_id, include_archived
    )


@mcp.tool(annotations=READ)
def get_character(
    project_id: Identifier, character_id: Identifier
) -> dict[str, Any]:
    """Get one character and a boolean indicating private-image availability."""
    return call(
        "aics.read", mcp_service.get_character, project_id, character_id
    )


@mcp.tool(annotations=READ)
def list_prompts(
    project_id: Identifier, include_archived: bool = False
) -> dict[str, Any]:
    """List reusable prompts in one caller-owned project."""
    return call(
        "aics.read", mcp_service.list_prompts, project_id, include_archived
    )


@mcp.tool(annotations=READ)
def list_production_gates(project_id: Identifier) -> dict[str, Any]:
    """List manual production gates without inferring approval from other text."""
    return call("aics.read", mcp_service.list_production_gates, project_id)


@mcp.tool(annotations=WRITE)
def update_project_bible(
    project_id: Identifier,
    expected_revision: Revision,
    changes: Annotated[dict[str, BoundedText], Field(min_length=1, max_length=9)],
) -> dict[str, Any]:
    """Partially update supported Bible fields and preserve every omitted field."""
    return call(
        "aics.write", mcp_service.update_project_bible,
        project_id, expected_revision, changes,
    )


@mcp.tool(annotations=WRITE)
def update_episode_planning(
    project_id: Identifier,
    episode_id: Identifier,
    expected_revision: Revision,
    synopsis: BoundedText | None = None,
    beats: BoundedText | None = None,
) -> dict[str, Any]:
    """Update synopsis and beats without changing the episode hook or script."""
    return call(
        "aics.write", mcp_service.update_episode_planning,
        project_id, episode_id, expected_revision, synopsis, beats,
    )


@mcp.tool(annotations=WRITE)
def replace_episode_shots(
    project_id: Identifier,
    episode_id: Identifier,
    expected_revision: Revision,
    shots: Annotated[list[dict[str, Any]], Field(max_length=200)],
) -> dict[str, Any]:
    """Replace only one episode's complete ordered shot plan after validation."""
    return call(
        "aics.write", mcp_service.replace_episode_shots,
        project_id, episode_id, expected_revision, shots,
    )


@mcp.tool(annotations=WRITE)
def update_character_planning(
    project_id: Identifier,
    character_id: Identifier,
    expected_revision: Revision,
    reference_requirements: Annotated[str, Field(max_length=10_000)] | None = None,
    continuity: Annotated[dict[str, str], Field(max_length=4)] | None = None,
) -> dict[str, Any]:
    """Partially update character reference requirements and continuity locks."""
    return call(
        "aics.write", mcp_service.update_character_planning,
        project_id, character_id, expected_revision,
        reference_requirements, continuity,
    )


@mcp.tool(annotations=WRITE)
def upsert_project_prompt(
    project_id: Identifier,
    expected_revision: Revision,
    name: Annotated[str, Field(min_length=1, max_length=120)],
    category: Annotated[str, Field(min_length=1, max_length=80)],
    body: BoundedText,
    prompt_id: Identifier | None = None,
    purpose: Annotated[str, Field(max_length=300)] = "",
    model_settings: Annotated[str, Field(max_length=5_000)] = "",
) -> dict[str, Any]:
    """Create or update a project prompt without changing shot prompt snapshots."""
    return call(
        "aics.write", mcp_service.upsert_project_prompt,
        project_id, expected_revision, name, category, body,
        prompt_id, purpose, model_settings,
    )


@mcp.tool(annotations=WRITE)
def update_production_gates(
    project_id: Identifier,
    expected_revision: Revision,
    gates: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=100)],
) -> dict[str, Any]:
    """Create or update manual gates without deleting omitted gates."""
    return call(
        "aics.write", mcp_service.update_production_gates,
        project_id, expected_revision, gates,
    )


@mcp.tool(annotations=ARCHIVE)
def archive_content_record(
    project_id: Identifier,
    record_type: Annotated[str, Field(pattern=r"^(project|episode|character|prompt)$")],
    record_id: Identifier,
    expected_revision: Revision,
) -> dict[str, Any]:
    """Archive one caller-owned project, episode, character, or prompt."""
    return call(
        "aics.write", mcp_service.set_archive_state,
        project_id, record_type, record_id, expected_revision, True,
    )


@mcp.tool(annotations=RESTORE)
def restore_content_record(
    project_id: Identifier,
    record_type: Annotated[str, Field(pattern=r"^(project|episode|character|prompt)$")],
    record_id: Identifier,
    expected_revision: Revision,
) -> dict[str, Any]:
    """Restore one caller-owned project, episode, character, or prompt."""
    return call(
        "aics.write", mcp_service.set_archive_state,
        project_id, record_type, record_id, expected_revision, False,
    )


@mcp.tool(annotations=DELETE)
def delete_project(
    project_id: Identifier,
    expected_revision: Revision,
    confirmation: Confirmation,
) -> dict[str, Any]:
    """Permanently delete one project and its nested content after exact-title confirmation."""
    return call(
        "aics.write", mcp_service.delete_project,
        project_id, expected_revision, confirmation,
    )


@mcp.tool(annotations=DELETE)
def delete_episode(
    project_id: Identifier,
    episode_id: Identifier,
    expected_revision: Revision,
    confirmation: Confirmation,
) -> dict[str, Any]:
    """Permanently delete one episode and its shots after exact-title confirmation."""
    return call(
        "aics.write", mcp_service.delete_episode,
        project_id, episode_id, expected_revision, confirmation,
    )


@mcp.tool(annotations=DELETE)
def delete_character(
    project_id: Identifier,
    character_id: Identifier,
    expected_revision: Revision,
    confirmation: Confirmation,
) -> dict[str, Any]:
    """Permanently delete one character and private image after exact-name confirmation."""
    return call(
        "aics.write", mcp_service.delete_character,
        project_id, character_id, expected_revision, confirmation,
    )


@mcp.tool(annotations=DELETE)
def delete_project_prompt(
    project_id: Identifier,
    prompt_id: Identifier,
    expected_revision: Revision,
    confirmation: Confirmation,
) -> dict[str, Any]:
    """Delete one prompt after exact-name confirmation while preserving shot snapshots."""
    return call(
        "aics.write", mcp_service.delete_project_prompt,
        project_id, prompt_id, expected_revision, confirmation,
    )


@mcp.tool(annotations=DELETE)
def delete_episode_shot(
    project_id: Identifier,
    episode_id: Identifier,
    shot_id: Identifier,
    expected_revision: Revision,
    confirmation: Confirmation,
) -> dict[str, Any]:
    """Permanently delete one unnamed shot after exact stable-ID confirmation."""
    return call(
        "aics.write", mcp_service.delete_episode_shot,
        project_id, episode_id, shot_id, expected_revision, confirmation,
    )


@mcp.tool(annotations=DELETE)
def delete_production_gate(
    project_id: Identifier,
    gate_id: Identifier,
    expected_revision: Revision,
    confirmation: Confirmation,
) -> dict[str, Any]:
    """Permanently delete one production gate after exact-name confirmation."""
    return call(
        "aics.write", mcp_service.delete_production_gate,
        project_id, gate_id, expected_revision, confirmation,
    )


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=server.MCP_INTERNAL_PORT,
        streamable_http_path="/mcp",
        json_response=True,
    )
