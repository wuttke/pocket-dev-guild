"""Drives the lifecycle of a single conversation turn.

Wraps `AugmentRunner.run` so that callers (the jobs/conversations routers)
don't have to know about session discovery or summary generation. The
conversation is marked `busy` for the entire wrapper so the router can
reject parallel turns with 409.
"""

from __future__ import annotations

from pathlib import Path

from .augment_runner import AugmentRunner
from .conversation_store import ConversationStore
from .job_store import JobStore


async def run_conversation_turn(
    *,
    conversation_id: str,
    job_id: str,
    cwd: Path,
    prompt: str,
    conversations: ConversationStore,
    jobs: JobStore,
    runner: AugmentRunner,
) -> None:
    """Run a conversation-bound job and post-process its session metadata.

    Always clears the conversation's `busy` flag, even on failure, so the
    next turn isn't permanently blocked by a crashed orchestrator task.
    """
    await conversations.mark_busy(conversation_id, True)
    try:
        conv = conversations.get(conversation_id)
        resume_session = conv.session_id if conv else None

        await runner.run(job_id, cwd, prompt, session_id=resume_session)

        job = jobs.get(job_id)
        if job is None:
            return

        session_id = resume_session
        if session_id is None and job.request_id:
            session_id = await runner.discover_session(job.request_id)
            if session_id:
                await conversations.patch(
                    conversation_id, session_id=session_id
                )
                await jobs.set_session_meta(job_id, session_id=session_id)

        if session_id and job.status == "finished":
            summary = await runner.summarize(session_id)
            if summary:
                await conversations.patch(conversation_id, summary=summary)
    finally:
        await conversations.mark_busy(conversation_id, False)
