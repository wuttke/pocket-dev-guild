"""Tests for conversation list with last_turn_status."""

import pytest

from pocket_dev_guild.services.conversation_store import ConversationStore
from pocket_dev_guild.services.job_store import JobStore


@pytest.mark.asyncio
async def test_list_with_turn_status_empty_conversations():
    """Conversations with no turns should have last_turn_status=None."""
    store = ConversationStore()
    jobs = JobStore()

    conv = await store.create("test-repo", None, None, "Test Conv")
    result = await store.list_with_turn_status(jobs)

    assert len(result) == 1
    assert result[0].id == conv.id
    assert result[0].last_turn_status is None


@pytest.mark.asyncio
async def test_list_with_turn_status_single_turn():
    """Conversation with one turn should show its status."""
    store = ConversationStore()
    jobs = JobStore()

    conv = await store.create("test-repo", None, None, "Test Conv")
    job = await jobs.create("test-repo", None, "test prompt", conversation_id=conv.id)
    await store.append_turn(conv.id, job.id)

    result = await store.list_with_turn_status(jobs)

    assert len(result) == 1
    assert result[0].id == conv.id
    assert result[0].last_turn_status == "queued"


@pytest.mark.asyncio
async def test_list_with_turn_status_multiple_turns():
    """Should show status of the most recent turn."""
    store = ConversationStore()
    jobs = JobStore()

    conv = await store.create("test-repo", None, None, "Test Conv")
    
    # First turn: finished
    job1 = await jobs.create("test-repo", None, "first", conversation_id=conv.id)
    await store.append_turn(conv.id, job1.id)
    await jobs.set_status(job1.id, "finished", returncode=0)
    
    # Second turn: running
    job2 = await jobs.create("test-repo", None, "second", conversation_id=conv.id)
    await store.append_turn(conv.id, job2.id)
    await jobs.set_status(job2.id, "running")

    result = await store.list_with_turn_status(jobs)

    assert len(result) == 1
    assert result[0].id == conv.id
    assert result[0].last_turn_status == "running"


@pytest.mark.asyncio
async def test_list_with_turn_status_multiple_conversations():
    """Should handle multiple conversations with different states."""
    store = ConversationStore()
    jobs = JobStore()

    # Conv 1: no turns
    conv1 = await store.create("test-repo", None, None, "No turns")
    
    # Conv 2: running turn
    conv2 = await store.create("test-repo", None, None, "Running")
    job2 = await jobs.create("test-repo", None, "prompt", conversation_id=conv2.id)
    await store.append_turn(conv2.id, job2.id)
    await jobs.set_status(job2.id, "running")
    
    # Conv 3: finished turn
    conv3 = await store.create("test-repo", None, None, "Finished")
    job3 = await jobs.create("test-repo", None, "prompt", conversation_id=conv3.id)
    await store.append_turn(conv3.id, job3.id)
    await jobs.set_status(job3.id, "finished", returncode=0)

    result = await store.list_with_turn_status(jobs)

    assert len(result) == 3
    
    # Find each conversation in results
    by_id = {c.id: c for c in result}
    
    assert by_id[conv1.id].last_turn_status is None
    assert by_id[conv2.id].last_turn_status == "running"
    assert by_id[conv3.id].last_turn_status == "finished"


def test_conversation_list_endpoint_includes_turn_status(client):
    """GET /api/conversations should include last_turn_status field."""
    # Create a conversation (using "demo" repo from conftest)
    resp = client.post("/api/conversations", json={
        "repo_id": "demo",
        "title": "Test"
    })
    assert resp.status_code == 200
    conv = resp.json()
    conv_id = conv["id"]

    # List should include the field (None for no turns)
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["last_turn_status"] is None

    # Create a turn
    resp = client.post(f"/api/conversations/{conv_id}/turns", json={
        "prompt": "test"
    })
    assert resp.status_code == 200

    # List should now show the turn status
    resp = client.get("/api/conversations")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    # Should be "queued" or "running" depending on timing
    assert data["items"][0]["last_turn_status"] in ["queued", "running", "finished", "failed"]
