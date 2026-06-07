"""Runs the `augment` CLI as a subprocess and streams output into a JobStore.

The runner also exposes two conversation helpers — `discover_session` (used
on the first turn of a conversation to learn auggie's session id from the
captured `Request ID`) and `summarize` (cheap JSON-mode summary turn). Both
shell out to `auggie` with `--mcp-config <empty.json>` so they don't pay
the MCP server boot cost.

Implemented as a Protocol so tests can inject a fake.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..schemas import LogLine
from .job_store import JobStore

# Strip CSI escape sequences before matching the Request ID line —
# auggie colors that line even when stdout is a pipe.
_ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_REQUEST_ID = re.compile(
    r"Request ID:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

DEFAULT_SUMMARY_PROMPT = (
    "Summarise this conversation so far in 3 to 5 sentences of plain text. "
    "Focus on what the user asked for and what was done. No markdown, no "
    "bullet lists, no preamble — just the summary."
)


class AugmentRunner(Protocol):
    async def run(
        self,
        job_id: str,
        cwd: Path,
        prompt: str,
        *,
        session_id: str | None = None,
    ) -> None: ...

    async def discover_session(self, request_id: str) -> str | None: ...

    async def summarize(
        self, session_id: str, prompt: str = DEFAULT_SUMMARY_PROMPT
    ) -> str | None: ...


@dataclass
class SubprocessAugmentRunner:
    """Default runner – spawns the configured agent binary."""

    store: JobStore
    binary: str = "auggie"
    prompt_param: str = "--print"
    # Lazily-created file containing `{"mcpServers": {}}`. Used by
    # `summarize` to skip MCP boot.
    _empty_mcp_config: Path | None = None

    async def run(
        self,
        job_id: str,
        cwd: Path,
        prompt: str,
        *,
        session_id: str | None = None,
    ) -> None:
        await self.store.set_status(job_id, "running")
        try:
            args: list[str] = [self.binary, self.prompt_param]
            if session_id is not None:
                args += ["--resume", session_id]
                await self.store.set_session_meta(job_id, session_id=session_id)
            args.append(prompt)

            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.gather(
                self._pump(process.stdout, job_id, "stdout", capture_ids=True),
                self._pump(process.stderr, job_id, "stderr", capture_ids=False),
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
        self,
        stream: asyncio.StreamReader | None,
        job_id: str,
        name: str,
        *,
        capture_ids: bool,
    ) -> None:
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            text = raw.decode(errors="replace")
            await self.store.append_log(
                job_id,
                LogLine(stream=name, line=text),  # type: ignore[arg-type]
            )
            if capture_ids:
                match = _REQUEST_ID.search(_ANSI_CSI.sub("", text))
                if match:
                    await self.store.set_session_meta(
                        job_id, request_id=match.group(1)
                    )

    def _empty_mcp(self) -> Path:
        if self._empty_mcp_config and self._empty_mcp_config.exists():
            return self._empty_mcp_config
        fd, path = tempfile.mkstemp(prefix="pdg-empty-mcp-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write('{"mcpServers": {}}')
        self._empty_mcp_config = Path(path)
        return self._empty_mcp_config

    async def discover_session(self, request_id: str) -> str | None:
        """Look up the auggie session whose `requestIds` contains `request_id`.

        Uses `auggie session list --all --json`. Returns None on any
        failure — the conversation stays usable, just without resume on
        subsequent turns until a later run rediscovers it.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary, "session", "list", "--all", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode != 0 or not stdout:
                return None
            payload = json.loads(stdout)
        except (OSError, json.JSONDecodeError):
            return None
        sessions = (
            payload if isinstance(payload, list) else payload.get("sessions", [])
        )
        for session in sessions:
            req_ids = session.get("requestIds") or []
            if request_id in req_ids:
                sid = session.get("sessionId") or session.get("id")
                if isinstance(sid, str):
                    return sid
        return None

    async def summarize(
        self, session_id: str, prompt: str = DEFAULT_SUMMARY_PROMPT
    ) -> str | None:
        """Run a cheap summary turn against an existing session.

        Resumes the session, disables MCP, doesn't persist the summary
        exchange in the session history. Returns the `.result` field of
        auggie's JSON output, or None on any failure.
        """
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary, self.prompt_param,
                "--resume", session_id,
                "--dont-save-session",
                "--mcp-config", str(self._empty_mcp()),
                "--output-format", "json",
                "-i", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if process.returncode != 0 or not stdout:
                return None
            payload = json.loads(stdout.splitlines()[-1])
        except (OSError, json.JSONDecodeError, IndexError):
            return None
        if payload.get("is_error"):
            return None
        result = payload.get("result")
        if not isinstance(result, str):
            return None
        return result.strip() or None
