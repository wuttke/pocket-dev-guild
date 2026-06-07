# Repository Migration Guide

## Overview

As of this version, repositories are no longer configured in `config.yaml`.
Instead, they are managed via API endpoints and persisted to the database
(when MongoDB is configured) or stored in-memory.

## Why This Change?

1. **Dynamic Management**: Add, update, and remove repositories without editing config files or restarting the service
2. **Database Persistence**: When using MongoDB, repositories persist across restarts just like jobs and conversations
3. **API-First**: Consistent with the REST API design for all resources
4. **Clone Support**: New ability to clone repositories directly from URLs via the API

## Migration Steps

### For Existing Deployments

If you have repositories defined in `config.yaml` and want to migrate:

#### 1. Ensure MongoDB is Configured (Recommended)

For persistent repository storage, configure MongoDB in `config.yaml`:

```yaml
mongodb_url: mongodb://localhost:27017/pocket_dev_guild
```

Without MongoDB, repositories will be stored in-memory and need to be
re-registered on each restart.

#### 2. Register Your Repositories

For each repository in your old `config.yaml`, register it via the API:

```bash
# Example for a repository at /home/user/my-project
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{
    "id": "my-project",
    "name": "My Project",
    "path": "/home/user/my-project"
  }'
```

**Important**: The path must point to an existing git repository on disk.
The endpoint will verify that:
- The path exists
- The path contains a `.git` directory

#### 3. Verify the Migration

List all registered repositories:

```bash
curl http://localhost:8000/repos
```

You should see your repositories in the response.

#### 4. Remove Old Config

Once verified, you can remove the `repos` section from `config.yaml`:

```yaml
# Before:
repos:
  - id: example
    name: example
    path: /absolute/path/to/example

# After (remove the repos section entirely):
# agent_binary: auggie
# mongodb_url: mongodb://localhost:27017/pocket_dev_guild
```

The old `repos` section is ignored when repositories are in the database.

### For New Deployments

Simply use the API endpoints to manage repositories:

#### Register an Existing Repository

```bash
curl -X POST http://localhost:8000/repos \
  -H "Content-Type: application/json" \
  -d '{
    "id": "my-repo",
    "name": "My Repository",
    "path": "/absolute/path/to/repo"
  }'
```

#### Clone a New Repository

```bash
curl -X POST http://localhost:8000/repos/clone \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://github.com/user/repo.git",
    "parent_path": "/home/user/projects",
    "id": "my-repo",
    "name": "My Repository"
  }'
```

The `id` and `name` fields are optional - if not provided, they will be
derived from the repository URL.

## API Reference

### List Repositories

```http
GET /repos
```

Returns an array of all registered repositories.

### Register a Repository

```http
POST /repos
Content-Type: application/json

{
  "id": "repo-id",        # Must match ^[A-Za-z0-9_-]+$
  "name": "Display Name",
  "path": "/absolute/path/to/repo"
}
```

**Requirements**:
- Path must exist
- Path must be a valid git repository (contains `.git`)
- ID must be unique

**Returns**: `200 OK` with the created repository object

**Errors**:
- `400 Bad Request`: Path doesn't exist or is not a git repository
- `409 Conflict`: Repository with that ID already exists

### Clone a Repository

```http
POST /repos/clone
Content-Type: application/json

{
  "url": "https://github.com/user/repo.git",
  "parent_path": "/absolute/path/to/parent",
  "id": "repo-id",      # Optional, derived from URL if not provided
  "name": "Repo Name"   # Optional, derived from URL if not provided
}
```

Clones the repository to `{parent_path}/{name}`.

**Returns**: `200 OK` with the created repository object

**Errors**:
- `400 Bad Request`: Parent path doesn't exist, clone failed, or target already exists
- `409 Conflict`: Repository with that ID already exists

## Automation

For automated setups, you can create a startup script to register repositories:

```bash
#!/bin/bash
# register-repos.sh

API_URL="http://localhost:8000"

# Wait for server to be ready
until curl -f "$API_URL/repos" > /dev/null 2>&1; do
  echo "Waiting for API..."
  sleep 1
done

# Register repositories
curl -X POST "$API_URL/repos" \
  -H "Content-Type: application/json" \
  -d '{"id": "repo1", "name": "Repo 1", "path": "/path/to/repo1"}'

curl -X POST "$API_URL/repos" \
  -H "Content-Type: application/json" \
  -d '{"id": "repo2", "name": "Repo 2", "path": "/path/to/repo2"}'
```

Run this script after starting the server to ensure repositories are
available (useful when running without MongoDB).
