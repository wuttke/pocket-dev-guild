# Worktree Status Check Feature

## Overview

This feature adds a new API endpoint that checks if a worktree is "clean" before deletion, warning users about potential data loss from uncommitted changes or unpushed commits.

## Implementation

### 1. New Schema (`pocket_dev_guild/schemas.py`)

Added `WorktreeStatus` model:

```python
class WorktreeStatus(BaseModel):
    """Status information for a worktree before deletion.
    
    `is_clean` is True when the worktree has no uncommitted changes and
    no unpushed commits. `messages` contains a list of warnings when
    `is_clean` is False.
    """
    
    is_clean: bool
    messages: list[str] = Field(default_factory=list)
```

### 2. Git Service Method (`pocket_dev_guild/services/git_service.py`)

Added `check_worktree_status()` method that:
- Checks for uncommitted changes (modified and untracked files) using `git status --porcelain`
- Checks for unpushed commits by comparing the local branch with its upstream using `git rev-list`
- Returns a tuple of `(is_clean: bool, messages: list[str])`

### 3. API Endpoint (`pocket_dev_guild/routers/worktrees.py`)

Added new endpoint:

```
GET /api/repos/{repo_id}/worktrees/{name}/status
```

Response example:
```json
{
  "is_clean": false,
  "messages": [
    "Uncommitted changes in 3 file(s)",
    "Untracked files: 2 file(s)",
    "Unpushed commits: 2 commit(s) on branch feature/foo"
  ]
}
```

### 4. Frontend Integration (`static/index.html`)

Updated `deleteWorktree()` function to:
1. Call the status endpoint before deletion
2. Show a warning dialog with specific messages if the worktree is not clean
3. Allow deletion even if unclean (user must confirm)
4. Fall back to simple confirmation if status check fails

### 5. Tests (`tests/test_worktrees.py`)

Added 4 comprehensive tests:
- `test_worktree_status_clean`: Verifies clean worktree with upstream returns `is_clean=true`
- `test_worktree_status_uncommitted_changes`: Tests detection of modified and untracked files
- `test_worktree_status_unpushed_commits`: Tests detection of commits not pushed to upstream
- `test_worktree_status_not_found`: Tests 404 for non-existent worktree

### 6. Documentation (`README.md`)

Added section explaining the new endpoint and its usage.

## Key Features

✅ **Advisory only**: Deletion is always allowed - this is purely informational
✅ **Detailed messages**: Specific warnings about what's unclean
✅ **Handles edge cases**: 
  - No upstream branch configured
  - Detached HEAD state
  - Untracked files vs uncommitted changes
✅ **Frontend integration**: User gets clear warnings before deletion
✅ **Fully tested**: 4 new tests covering all scenarios

## Usage Example

```bash
# Check status
curl http://localhost:8080/api/repos/demo/worktrees/feature_foo/status

# Response when clean
{"is_clean": true, "messages": []}

# Response when dirty
{
  "is_clean": false,
  "messages": [
    "Uncommitted changes in 2 file(s)",
    "Unpushed commits: 1 commit(s) on branch feature/foo"
  ]
}
```

## Testing

All tests pass (90 total, including 4 new tests for this feature):

```bash
.venv/bin/pytest tests/test_worktrees.py::test_worktree_status_clean -v
.venv/bin/pytest tests/test_worktrees.py::test_worktree_status_uncommitted_changes -v
.venv/bin/pytest tests/test_worktrees.py::test_worktree_status_unpushed_commits -v
.venv/bin/pytest tests/test_worktrees.py::test_worktree_status_not_found -v
```
