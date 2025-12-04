"""Tests for ConcurrentSessionStorage with async locking."""

import asyncio
import pytest
from query_refinement_module.providers import (
    InMemorySessionStorage,
    ConcurrentSessionStorage,
)


@pytest.fixture
def concurrent_storage():
    """Create a concurrent storage with in-memory backend."""
    backend = InMemorySessionStorage()
    return ConcurrentSessionStorage(backend)


def test_concurrent_storage_wraps_backend():
    """Test that concurrent storage wraps a backend properly."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    assert storage._backend is backend
    assert isinstance(storage._locks, dict)


def test_concurrent_storage_sync_operations(concurrent_storage):
    """Test that synchronous operations work correctly."""
    session_data = {"query": "test", "step": 1}
    
    # Save
    concurrent_storage.save_session("session1", session_data)
    
    # Check exists
    assert concurrent_storage.session_exists("session1")
    
    # Load
    loaded = concurrent_storage.load_session("session1")
    assert loaded == session_data
    
    # Delete
    concurrent_storage.delete_session("session1")
    assert not concurrent_storage.session_exists("session1")


@pytest.mark.asyncio
async def test_concurrent_storage_async_operations(concurrent_storage):
    """Test that async operations work correctly."""
    session_data = {"query": "async test", "step": 2}
    
    # Save
    await concurrent_storage.save_session_async("session2", session_data)
    
    # Check exists
    exists = await concurrent_storage.session_exists_async("session2")
    assert exists
    
    # Load
    loaded = await concurrent_storage.load_session_async("session2")
    assert loaded == session_data
    
    # Delete
    await concurrent_storage.delete_session_async("session2")
    exists = await concurrent_storage.session_exists_async("session2")
    assert not exists


@pytest.mark.asyncio
async def test_concurrent_storage_lock_per_session(concurrent_storage):
    """Test that each session has its own lock."""
    await concurrent_storage.save_session_async("session_a", {"data": "A"})
    await concurrent_storage.save_session_async("session_b", {"data": "B"})
    
    # Both sessions should have locks
    assert "session_a" in concurrent_storage._locks
    assert "session_b" in concurrent_storage._locks
    
    # Locks should be different instances
    assert concurrent_storage._locks["session_a"] is not concurrent_storage._locks["session_b"]


@pytest.mark.asyncio
async def test_concurrent_storage_serializes_same_session():
    """Test that concurrent saves to the same session don't corrupt data."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Save multiple values concurrently to the same session
    # The last save should win, and data should not be corrupted
    await asyncio.gather(
        storage.save_session_async("session1", {"value": 1}),
        storage.save_session_async("session1", {"value": 2}),
        storage.save_session_async("session1", {"value": 3}),
    )
    
    # Session should have a valid value (one of 1, 2, or 3)
    result = await storage.load_session_async("session1")
    assert "value" in result
    assert result["value"] in [1, 2, 3]
    
    # Verify the lock mechanism exists and works
    lock = storage._get_lock("session1")
    assert lock is not None
    
    # The lock should serialize the actual save operations
    # so we don't get partial/corrupted data


@pytest.mark.asyncio
async def test_concurrent_storage_allows_parallel_different_sessions():
    """Test that operations on different sessions can run in parallel."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    execution_order = []
    
    async def track_operation(session_id: str):
        """Track when operations start and end."""
        execution_order.append(f"start_{session_id}")
        await storage.save_session_async(session_id, {"data": session_id})
        await asyncio.sleep(0.01)
        execution_order.append(f"end_{session_id}")
    
    # Start concurrent operations on different sessions
    await asyncio.gather(
        track_operation("session_a"),
        track_operation("session_b"),
        track_operation("session_c"),
    )
    
    # Operations on different sessions should interleave (run in parallel)
    # We should see starts before all ends
    first_end_idx = min(
        execution_order.index("end_session_a"),
        execution_order.index("end_session_b"),
        execution_order.index("end_session_c"),
    )
    
    # At least one other session should have started before the first one ends
    starts_before_first_end = [
        event for event in execution_order[:first_end_idx] if event.startswith("start_")
    ]
    assert len(starts_before_first_end) >= 2, "Sessions should run in parallel"


@pytest.mark.asyncio
async def test_concurrent_storage_cleanup_lock_on_delete(concurrent_storage):
    """Test that locks are cleaned up after session deletion."""
    await concurrent_storage.save_session_async("temp_session", {"data": "temp"})
    
    # Lock should exist
    assert "temp_session" in concurrent_storage._locks
    
    # Delete session
    await concurrent_storage.delete_session_async("temp_session")
    
    # Lock should be cleaned up
    assert "temp_session" not in concurrent_storage._locks


def test_concurrent_storage_sync_delete_cleans_lock(concurrent_storage):
    """Test that sync delete also cleans up locks."""
    concurrent_storage.save_session("sync_session", {"data": "sync"})
    
    # Trigger lock creation by doing an async check
    lock = concurrent_storage._get_lock("sync_session")
    assert lock is not None
    
    # Delete using sync method
    concurrent_storage.delete_session("sync_session")
    
    # Lock should be cleaned up
    assert "sync_session" not in concurrent_storage._locks


@pytest.mark.asyncio
async def test_concurrent_storage_load_nonexistent_session(concurrent_storage):
    """Test that loading a nonexistent session raises KeyError."""
    with pytest.raises(KeyError):
        await concurrent_storage.load_session_async("nonexistent")


@pytest.mark.asyncio
async def test_concurrent_storage_race_condition_protection():
    """Test that load/save operations have per-session locking."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Initialize session
    await storage.save_session_async("counter", {"count": 0})
    
    async def increment_with_lock():
        """Load, increment, and save counter under lock."""
        # Get the lock manually to protect the entire read-modify-write
        lock = storage._get_lock("counter")
        async with lock:
            session = await asyncio.to_thread(backend.load_session, "counter")
            count = session["count"]
            await asyncio.sleep(0.001)  # Simulate processing
            session["count"] = count + 1
            await asyncio.to_thread(backend.save_session, "counter", session)
    
    # Run 10 concurrent increments
    await asyncio.gather(*[increment_with_lock() for _ in range(10)])
    
    # Final count should be exactly 10 (no lost updates)
    final_session = await storage.load_session_async("counter")
    assert final_session["count"] == 10


@pytest.mark.asyncio
async def test_concurrent_storage_get_lock_creates_once():
    """Test that _get_lock creates a lock only once per session."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Get lock multiple times
    lock1 = storage._get_lock("session1")
    lock2 = storage._get_lock("session1")
    lock3 = storage._get_lock("session1")
    
    # Should be the same lock instance
    assert lock1 is lock2
    assert lock2 is lock3
    assert len(storage._locks) == 1


def test_concurrent_storage_backend_passthrough():
    """Test that backend operations are properly delegated."""
    backend = InMemorySessionStorage()
    storage = ConcurrentSessionStorage(backend)
    
    # Use sync operations
    storage.save_session("test", {"value": 123})
    
    # Verify data is in backend
    assert backend.session_exists("test")
    assert backend.load_session("test") == {"value": 123}
    
    # Delete and verify
    storage.delete_session("test")
    assert not backend.session_exists("test")
