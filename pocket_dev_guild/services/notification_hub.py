"""In-memory notification hub for real-time SSE updates.

Manages asyncio.Condition objects for pushing updates to SSE streams.
Lives only in the current server process — after restart, clients
reconnect and conditions are recreated on first wait.

Thread-unsafe by design: runs entirely on the asyncio event loop.
"""

from __future__ import annotations

import asyncio


class NotificationHub:
    """Manages in-memory notifications for real-time updates."""

    def __init__(self) -> None:
        self._conditions: dict[str, asyncio.Condition] = {}

    async def notify(self, key: str) -> None:
        """Wake up all waiters on the given key.
        
        If no condition exists for this key, this is a no-op.
        """
        cond = self._conditions.get(key)
        if cond:
            async with cond:
                cond.notify_all()

    async def wait(self, key: str, timeout: float = 5.0) -> None:
        """Wait for a notification on the given key, or timeout.
        
        Creates a condition if one doesn't exist yet. This allows
        SSE streams to connect after server restart and still work.
        """
        if key not in self._conditions:
            self._conditions[key] = asyncio.Condition()
        
        async with self._conditions[key]:
            try:
                await asyncio.wait_for(self._conditions[key].wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
