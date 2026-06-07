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

    async def _resolve_remote(self, repo_path: Path) -> str:
        """Pick the remote to branch off.

        Prefers `origin` if present (the overwhelmingly common case);
        otherwise the single configured remote; otherwise raises.
        """
        code, out, err = await self._run(["remote"], repo_path)
        if code != 0:
            raise GitError(err.strip() or "git remote failed", code)
        remotes = [r for r in out.split() if r]
        if not remotes:
            raise GitError("repo has no remotes", 1)
        if "origin" in remotes:
            return "origin"
        if len(remotes) == 1:
            return remotes[0]
        raise GitError(
            f"ambiguous: multiple remotes {remotes!r}, none called 'origin'",
            1,
        )

    async def default_remote_branch(self, repo_path: Path) -> str:
        """Return the short ref of the default branch on the picked remote.

        Resolves `refs/remotes/<remote>/HEAD` to e.g. `origin/main` or
        `upstream/master`. Raises `GitError` if the symbolic ref is not
        set (never fetched, remote HEAD detached, etc).
        """
        remote = await self._resolve_remote(repo_path)
        code, out, err = await self._run(
            ["symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD"],
            repo_path,
        )
        if code != 0:
            raise GitError(
                err.strip() or f"could not resolve {remote}/HEAD", code
            )
        return out.strip()

    async def add_worktree(
        self,
        repo_path: Path,
        target: Path,
        *,
        branch: str,
        start_point: str | None = None,
    ) -> None:
        """Create `target` as a worktree for `branch`.

        With `start_point` set, runs `git worktree add -b <branch>
        <target> <start_point>` and so requires `branch` to be new.
        With `start_point=None`, runs `git worktree add <target>
        <branch>` to check out an existing branch (local or remote
        tracking); git fails if no such branch exists.
        """
        target.parent.mkdir(parents=True, exist_ok=True)
        if start_point is not None:
            args = ["worktree", "add", "-b", branch, str(target), start_point]
        else:
            args = ["worktree", "add", str(target), branch]
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
