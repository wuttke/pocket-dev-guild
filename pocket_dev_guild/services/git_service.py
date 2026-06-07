"""Thin async wrapper around `git worktree`.

Kept free of FastAPI imports so it can be unit-tested in isolation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from ..schemas import WorktreeInfo


class GitError(RuntimeError):
    """Raised when a git invocation exits non-zero."""

    def __init__(self, message: str, returncode: int) -> None:
        super().__init__(message)
        self.returncode = returncode


@dataclass
class GitService:
    git_binary: str = "git"

    async def _run(self, args: list[str], cwd: Path) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            self.git_binary, *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await process.communicate()
        return (
            process.returncode if process.returncode is not None else -1,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )

    async def list_worktrees(self, repo_path: Path) -> list[WorktreeInfo]:
        code, out, err = await self._run(["worktree", "list", "--porcelain"], repo_path)
        if code != 0:
            raise GitError(err.strip() or "git worktree list failed", code)
        return [_parse_worktree(block) for block in _split_porcelain(out)]

    async def add_worktree(
        self, repo_path: Path, target: Path, base_branch: str | None = None
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        args = ["worktree", "add", str(target)]
        if base_branch:
            args.append(base_branch)
        code, _, err = await self._run(args, repo_path)
        if code != 0:
            raise GitError(err.strip() or "git worktree add failed", code)

    async def remove_worktree(self, repo_path: Path, target: Path) -> None:
        code, _, err = await self._run(
            ["worktree", "remove", "--force", str(target)], repo_path
        )
        if code != 0:
            raise GitError(err.strip() or "git worktree remove failed", code)


def _split_porcelain(out: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_worktree(lines: list[str]) -> WorktreeInfo:
    data: dict[str, object] = {}
    for line in lines:
        key, _, value = line.partition(" ")
        if key in ("bare", "detached"):
            data[key] = True
        elif key == "worktree":
            data["path"] = value
        elif key == "HEAD":
            data["HEAD"] = value
        elif key == "branch":
            data["branch"] = value
    return WorktreeInfo(**data)  # type: ignore[arg-type]
