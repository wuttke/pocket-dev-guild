"""Runs the `augment` CLI as a subprocess and streams output into a JobStore.

Implemented as a Protocol so tests can inject a fake.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..schemas import LogLine
from .job_store import JobStore


class AugmentRunner(Protocol):
    async def run(self, job_id: str, cwd: Path, prompt: str) -> None: ...


@dataclass
class SubprocessAugmentRunner:
    """Default runner – spawns the configured agent binary."""

    store: JobStore
    binary: str = "auggie"
    prompt_param: str = "--print"

    async def run(self, job_id: str, cwd: Path, prompt: str) -> None:
        await self.store.set_status(job_id, "running")
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary, self.prompt_param, prompt,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.gather(
                self._pump(process.stdout, job_id, "stdout"),
                self._pump(process.stderr, job_id, "stderr"),
            )
            returncode = await process.wait()
            await self.store.set_status(
                job_id,
                "finished" if returncode == 0 else "failed",
                returncode=returncode,
            )
        except Exception as exc:  # noqa: BLE001 — surface to the log stream
            await self.store.append_log(
                job_id, LogLine(stream="stderr", line=f"{exc}\n")
            )
            await self.store.set_status(job_id, "failed", returncode=-1)

    async def _pump(
        self, stream: asyncio.StreamReader | None, job_id: str, name: str
    ) -> None:
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            await self.store.append_log(
                job_id,
                LogLine(stream=name, line=raw.decode(errors="replace")),  # type: ignore[arg-type]
            )
