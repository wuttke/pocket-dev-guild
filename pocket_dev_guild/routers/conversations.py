"""Conversations resource: multi-turn job groups sharing an agent session."""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sse_starlette.sse import EventSourceResponse

from ..config import RepoRegistry
from ..deps import get_conversations, get_registry, get_runner, get_store
from ..schemas import (
    IDENT_PATTERN,
    ConversationCreate,
    ConversationInfo,
    ConversationTurnCreate,
    JobCreated,
)
from ..services.augment_runner import AugmentRunner
from ..services.conversation_store import ConversationStore
from ..services.job_store import JobStore
from .jobs import start_job

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationInfo, summary="Start a conversation")
def create_conversation(
    body: ConversationCreate,
    registry: RepoRegistry = Depends(get_registry),
    conversations: ConversationStore = Depends(get_conversations),
) -> ConversationInfo:
    repo = registry.get(body.repo_id)
    if repo is None:
        raise HTTPException(404, f"Repo '{body.repo_id}' not found")
    if body.worktree is not None:
        target = registry.worktree_path(repo, body.worktree)
        if not target.exists():
            raise HTTPException(
                404, f"Worktree '{body.worktree}' not found at {target}"
            )
    return conversations.create(
        repo_id=body.repo_id,
        worktree=body.worktree,
        agent_id=body.agent_id,
        title=body.title,
    )


@router.get(
    "", response_model=list[ConversationInfo], summary="List conversations"
)
async def list_conversations(
    repo_id: Annotated[str | None, Query(pattern=IDENT_PATTERN)] = None,
    conversations: ConversationStore = Depends(get_conversations),
) -> list[ConversationInfo]:
    return await conversations.list(repo_id=repo_id)


@router.get(
    "/{conversation_id}",
    response_model=ConversationInfo,
    summary="Get a conversation",
)
async def get_conversation(
    conversation_id: Annotated[str, Path(min_length=1)],
    conversations: ConversationStore = Depends(get_conversations),
) -> ConversationInfo:
    conv = await conversations.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    return conv


@router.post(
    "/{conversation_id}/turns",
    response_model=JobCreated,
    summary="Start the next turn in a conversation",
)
async def create_turn(
    conversation_id: Annotated[str, Path(min_length=1)],
    body: ConversationTurnCreate,
    registry: RepoRegistry = Depends(get_registry),
    store: JobStore = Depends(get_store),
    runner: AugmentRunner = Depends(get_runner),
    conversations: ConversationStore = Depends(get_conversations),
) -> JobCreated:
    conv = await conversations.get(conversation_id)
    if conv is None:
        raise HTTPException(404, "Conversation not found")
    return await start_job(
        repo_id=conv.repo_id,
        worktree=conv.worktree,
        prompt=body.prompt,
        conversation_id=conversation_id,
        registry=registry,
        store=store,
        runner=runner,
        conversations=conversations,
    )


@router.get(
    "/{conversation_id}/events",
    summary="SSE stream of conversation state changes",
)
async def stream_conversation_events(
    conversation_id: Annotated[str, Path(min_length=1)],
    conversations: ConversationStore = Depends(get_conversations),
) -> EventSourceResponse:
    """Push the full conversation snapshot on every change.

    Emits an initial `snapshot` event, then an `update` event each time
    the underlying record is mutated (new turn appended, busy flag
    toggles, session_id resolved, summary refreshed). The payload always
    carries the entire `ConversationInfo` plus a top-level `busy` flag —
    the UI diffs against its local copy to figure out what changed.
    """
    if conversations.get(conversation_id) is None:
        raise HTTPException(404, "Conversation not found")
    return EventSourceResponse(
        _conversation_event_stream(conversations, conversation_id)
    )


async def _conversation_event_stream(
    conversations: ConversationStore, conversation_id: str
):
    """Yield SSE events for a conversation's lifetime.

    Emits an initial `snapshot`, then an `update` whenever the underlying
    record or busy flag changes. Extracted from the route so tests can
    drive it directly without going through `TestClient` (which buffers
    ASGI responses until the body completes).
    """

    def _payload(info: ConversationInfo, busy: bool) -> str:
        return json.dumps(
            {"conversation": info.model_dump(mode="json"), "busy": busy}
        )

    state = conversations.state(conversation_id)
    if state is None:
        yield {"event": "error", "data": "Conversation not found"}
        return
    info, busy = state
    last_signature = (info.model_dump_json(), busy)
    yield {"event": "snapshot", "data": _payload(info, busy)}

    while True:
        await conversations.wait_for_update(conversation_id, timeout=15.0)
        state = conversations.state(conversation_id)
        if state is None:
            yield {"event": "error", "data": "Conversation gone"}
            return
        info, busy = state
        signature = (info.model_dump_json(), busy)
        if signature != last_signature:
            last_signature = signature
            yield {"event": "update", "data": _payload(info, busy)}
