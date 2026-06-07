# Frontend Developer Guide

> **Pocket Dev Guild** — A web application for managing git worktrees and running AI coding agents with real-time output streaming.

## Table of Contents

1. [Overview](#overview)
2. [Current State](#current-state)
3. [API Reference](#api-reference)
4. [Data Structures](#data-structures)
5. [Real-time Communication](#real-time-communication)
6. [Proposed Mobile-First UI](#proposed-mobile-first-ui)
7. [Implementation Recommendations](#implementation-recommendations)
8. [Security Considerations](#security-considerations)

---

## Overview

Pocket Dev Guild is a FastAPI backend that provides a REST API for:
- **Repository Management**: List configured git repositories
- **Worktree Operations**: Create, list, and delete git worktrees
- **Job Execution**: Run AI coding agents (auggie, claude, etc.) with live log streaming
- **Conversations**: Multi-turn sessions that maintain agent context across runs

The application is designed to be accessed primarily via mobile devices, with real-time updates delivered through Server-Sent Events (SSE).

---

## Current State

### Existing Frontend
- **Location**: `static/index.html`
- **Size**: ~260 lines of vanilla JavaScript
- **Features**:
  - Repository selection dropdown
  - **Worktree management**: list, create (new or existing branch), **delete**
  - **Conversation support**: create, list, send turns, real-time updates via SSE
  - Real-time log streaming via SSE
- **Limitations** (frontend only — backend now supports all of these):
  - No job history/list view UI (backend `GET /jobs` exists)
  - No paginated list UI (backend paginates `/jobs` and `/conversations`)
  - No mobile optimization
  - Basic UI with minimal styling
  - No archive UI beyond the simple "Archivieren" button (no archived view)

### Tech Stack (Current)
- Vanilla JavaScript (ES6+)
- Server-Sent Events (EventSource API)
- No build process
- No CSS framework

---

## API Reference

### Base URL
- **Development**: `http://localhost:8000`
- **Production**: Configure via environment

### OpenAPI Documentation
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### Endpoints

#### Repositories

##### `GET /repos`
List all configured repositories.

**Response**: `200 OK`
```json
[
  {
    "id": "my-project",
    "name": "My Project",
    "path": "/home/user/repos/my-project"
  }
]
```

#### Worktrees

##### `GET /repos/{repo_id}/worktrees`
List all worktrees for a repository.

**Response**: `200 OK`
```json
[
  {
    "name": null,
    "is_primary": true,
    "path": "/home/user/repos/my-project",
    "branch": "main",
    "head": "abc123...",
    "bare": false,
    "detached": false
  },
  {
    "name": "feature_new-ui",
    "is_primary": false,
    "path": "/home/user/repos/my-project-worktrees/feature_new-ui",
    "branch": "feature/new-ui",
    "head": "def456...",
    "bare": false,
    "detached": false
  }
]
```

##### `POST /repos/{repo_id}/worktrees`
Create a new worktree.

**Query Parameters**:
- `existing` (optional, boolean): Set to `true` to check out an existing branch instead of creating a new one. Default: `false`.

**Request Body**:
```json
{
  "branch": "feature/new-feature"
}
```

**Response**: `200 OK`
```json
{
  "name": "feature_new_feature",
  "path": "/home/user/repos/my-project-worktrees/feature_new_feature"
}
```

**Notes**:
- **Branch name pattern**: `^[A-Za-z]+(/[A-Za-z0-9.-]+)+$`
  - First segment: letters only (e.g., `feature`, `Hotfix`, `release`)
  - Subsequent segments: letters, digits, dashes, and dots (e.g., `2.5.x`, `foo-bar`)
  - Valid examples: `feature/auth`, `Hotfix/critical-bug`, `release/2.5.x`
- **Worktree directory naming**:
  - Derived by lowercasing the branch name and replacing `/` and `.` with `_`
  - Example: `Feature/Auth` → `feature_auth`, `release/2.5.x` → `release_2_5_x`
  - This ensures case-insensitive filesystems handle `Feature/Foo` and `feature/foo` as the same worktree
- **Creating new branches** (`existing=false`, default):
  - Automatically branches from the default remote branch (usually `origin/main`)
  - Fails if branch already exists
- **Checking out existing branches** (`existing=true`):
  - Checks out an existing local or remote-tracking branch
  - Fails if branch doesn't exist

##### `DELETE /repos/{repo_id}/worktrees/{name}`
Remove a worktree.

**Response**: `200 OK`
```json
{
  "removed": "feature_new-feature"
}
```

#### Jobs

**Note**: Jobs are only created through conversations. There is no standalone job creation endpoint. Use `POST /conversations/{id}/turns` to create jobs within a conversation context.

##### `GET /jobs/{job_id}`
Get job metadata.

**Response**: `200 OK`
```json
{
  "id": "a1b2c3d4e5f6...",
  "repo_id": "my-project",
  "worktree": "feature_new-feature",
  "prompt": "Add unit tests for the authentication module",
  "status": "running",
  "returncode": null,
  "created_at": "2026-06-07T10:30:00Z",
  "finished_at": null,
  "conversation_id": null,
  "request_id": "uuid-here",
  "session_id": null
}
```

**Status Values**:
- `queued`: Job created but not yet started
- `running`: Job is currently executing
- `finished`: Job completed successfully
- `failed`: Job terminated with error

##### `GET /jobs/{job_id}/log`
Get full log snapshot (non-streaming).

**Response**: `200 OK`
```json
{
  "id": "a1b2c3d4e5f6...",
  "repo_id": "my-project",
  "worktree": "feature_new-feature",
  "prompt": "Add unit tests...",
  "status": "running",
  "returncode": null,
  "created_at": "2026-06-07T10:30:00Z",
  "finished_at": null,
  "conversation_id": null,
  "request_id": null,
  "session_id": null,
  "log": [
    {
      "stream": "stdout",
      "line": "Starting agent...\n"
    },
    {
      "stream": "stderr",
      "line": "Warning: Large file detected\n"
    }
  ]
}
```

##### `GET /jobs/{job_id}/events`
**Real-time SSE stream** of log lines and status updates.

**Events**:

1. **`log` event** (continuous):
```json
{
  "stream": "stdout",
  "line": "Processing file main.py\n"
}
```

2. **`status` event** (final):
```json
{
  "status": "finished",
  "returncode": 0,
  "finished_at": "2026-06-07T10:35:22Z"
}
```

#### Conversations

##### `POST /conversations`
Create a new conversation.

**Request Body**:
```json
{
  "repo_id": "my-project",
  "worktree": "feature_new-feature",
  "agent_id": null,
  "title": "Implement authentication"
}
```

**Response**: `200 OK`
```json
{
  "id": "conv-abc123...",
  "repo_id": "my-project",
  "worktree": "feature_new-feature",
  "agent_id": null,
  "title": "Implement authentication",
  "session_id": null,
  "summary": null,
  "created_at": "2026-06-07T10:00:00Z",
  "updated_at": "2026-06-07T10:00:00Z",
  "turns": []
}
```

##### `GET /conversations`
Paginated list of conversations with filtering and sorting.

**Query Parameters**:
- `repo_id` (optional): Filter by repository
- `worktree` (optional): Filter by worktree name
- `include_archived` (optional, default `false`): include soft-archived conversations
- `limit` (optional, default `50`, max `200`)
- `offset` (optional, default `0`)
- `sort` (optional, default `-updated_at`): comma-separated list, `-` prefix = desc.
  Allow-list: `updated_at`, `created_at`. Unknown fields → `400`.

**Still open (Backend)**:
- [ ] Add `updated_since` / status-style filters

**Response**: `200 OK`
```json
{
  "items": [
    {
      "id": "conv-abc123...",
      "repo_id": "my-project",
      "worktree": "feature_new-feature",
      "agent_id": null,
      "title": "Implement authentication",
      "session_id": "session-xyz...",
      "summary": "Working on adding JWT authentication to the API",
      "archived": false,
      "created_at": "2026-06-07T10:00:00Z",
      "updated_at": "2026-06-07T10:45:00Z",
      "turns": ["job-1", "job-2", "job-3"]
    }
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

##### `GET /conversations/{conversation_id}`
Get conversation details.

**Response**: `200 OK` (same as conversation object above)

##### `POST /conversations/{conversation_id}/turns`
Add a new turn to an existing conversation.

**Request Body**:
```json
{
  "prompt": "Now add unit tests for the login endpoint"
}
```

**Response**: `200 OK`
```json
{
  "job_id": "job-xyz789..."
}
```

**Notes**:
- Automatically resumes the agent session
- Returns `409 Conflict` if a turn is already in progress
- The job can be monitored via `GET /jobs/{job_id}/events`

##### `GET /conversations/{conversation_id}/events`
**Real-time SSE stream** of conversation state changes.

**Events**:

1. **`snapshot` event** (initial):
```json
{
  "conversation": {
    "id": "conv-abc123...",
    "repo_id": "my-project",
    "worktree": "feature_new-feature",
    "agent_id": null,
    "title": "Implement authentication",
    "session_id": "session-xyz...",
    "summary": "Working on JWT authentication",
    "created_at": "2026-06-07T10:00:00Z",
    "updated_at": "2026-06-07T10:45:00Z",
    "turns": ["job-1", "job-2"]
  },
  "busy": false
}
```

2. **`update` event** (on changes):
```json
{
  "conversation": { /* updated conversation object */ },
  "busy": true
}
```

The `busy` flag indicates whether a turn is currently in progress.

##### `DELETE /conversations/{conversation_id}`
Soft-archive a conversation. The row is kept so that historical jobs
can still resolve their `conversation_id`; subsequent `POST .../turns`
returns `409 Conflict`. Default `GET /conversations` hides archived
records; pass `?include_archived=true` to see them.

**Response**: `204 No Content` on success, `404 Not Found` if unknown.

### Job list

#### `GET /jobs`
Paginated list of jobs with filtering and sorting.

**Query Parameters**:
- `repo_id` (optional): Filter by repository
- `worktree` (optional): Filter by worktree name
- `status` (optional): `queued` | `running` | `finished` | `failed`. Anything else → `400`.
- `conversation_id` (optional): Filter by conversation
- `limit` (optional, default `50`, max `200`)
- `offset` (optional, default `0`)
- `sort` (optional, default `-created_at`): comma-separated list, `-` prefix = desc.
  Allow-list: `created_at`, `finished_at`, `status`. Unknown fields → `400`.

**Response**: `200 OK`
```json
{
  "items": [
    {
      "id": "job-123",
      "repo_id": "my-project",
      "worktree": "feature_auth",
      "prompt": "Add unit tests...",
      "status": "finished",
      "returncode": 0,
      "created_at": "2026-06-07T10:00:00Z",
      "finished_at": "2026-06-07T10:05:00Z",
      "conversation_id": "conv-abc"
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

**Validation**:
- `limit=0` / `limit>200` / `offset<0` → `422` (FastAPI bounds).
- Unknown `sort` field or `status` value → `400`.

---

## Data Structures

### TypeScript Interfaces

```typescript
// Repositories
interface Repo {
  id: string;          // Matches ^[A-Za-z0-9_-]+$
  name: string;
  path: string;
}

// Worktrees
interface WorktreeInfo {
  name: string | null;        // null for primary checkout
  is_primary: boolean;
  path: string | null;
  branch: string | null;
  head: string | null;        // Git commit hash
  bare: boolean;
  detached: boolean;
}

interface WorktreeCreate {
  branch: string;             // Matches ^[A-Za-z]+(/[A-Za-z0-9.-]+)+$
}

// Query parameter for creating worktrees
interface WorktreeCreateParams {
  existing?: boolean;         // true = checkout existing branch, false = create new (default)
}

interface WorktreeCreated {
  name: string;
  path: string;
}

// Jobs
type JobStatus = 'queued' | 'running' | 'finished' | 'failed';
type LogStream = 'stdout' | 'stderr';

// Note: Jobs are only created through conversation turns
// No standalone JobCreate - use ConversationTurnCreate instead

interface JobInfo {
  id: string;
  repo_id: string;
  worktree: string | null;
  prompt: string;
  status: JobStatus;
  returncode: number | null;
  created_at: string;         // ISO 8601
  finished_at: string | null; // ISO 8601
  conversation_id: string | null;
  request_id: string | null;  // Agent-specific request ID
  session_id: string | null;  // Agent session ID
}

interface LogLine {
  stream: LogStream;
  line: string;               // Includes \n
}

interface JobLog extends JobInfo {
  log: LogLine[];
}

// Conversations
interface ConversationCreate {
  repo_id: string;
  worktree: string | null;
  agent_id: string | null;
  title: string | null;
}

interface ConversationInfo {
  id: string;
  repo_id: string;
  worktree: string | null;
  agent_id: string | null;
  title: string | null;
  session_id: string | null;
  summary: string | null;
  archived: boolean;
  created_at: string;         // ISO 8601
  updated_at: string;         // ISO 8601
  turns: string[];            // Array of job IDs
}

// Paginated list wrapper used by GET /jobs and GET /conversations
interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// SSE Events
interface JobStatusEvent {
  status: JobStatus;
  returncode: number | null;
  finished_at: string | null;
}

interface ConversationStateEvent {
  conversation: ConversationInfo;
  busy: boolean;
}
```

---

## Real-time Communication

### Server-Sent Events (SSE)

The application uses **Server-Sent Events** for real-time updates. SSE is a one-way communication channel from server to client, perfect for live logs and status updates.

#### Browser Support
- ✅ All modern browsers (Chrome, Firefox, Safari, Edge)
- ✅ iOS Safari (native EventSource API)
- ✅ Android Chrome
- ❌ No support in IE11 (polyfills available)

#### Implementation Pattern

```javascript
// Connect to SSE endpoint
const eventSource = new EventSource('/jobs/abc123/events');

// Listen for specific event types
eventSource.addEventListener('log', (event) => {
  const logLine = JSON.parse(event.data);
  console.log(`[${logLine.stream}] ${logLine.line}`);
});

eventSource.addEventListener('status', (event) => {
  const status = JSON.parse(event.data);
  console.log(`Job ${status.status}, exit code: ${status.returncode}`);
  eventSource.close(); // Job is finished
});

eventSource.addEventListener('error', () => {
  console.error('SSE connection error');
  eventSource.close();
});

// Clean up when done
// eventSource.close();
```

#### Best Practices

1. **Always close connections**: Call `eventSource.close()` when done to prevent memory leaks
2. **Handle reconnection**: EventSource auto-reconnects, but you may want custom logic
3. **Parse JSON safely**: Always use `try/catch` when parsing `event.data`
4. **Mobile considerations**:
   - Close SSE when app goes to background to save battery
   - Reconnect when app returns to foreground
   - Consider using visibility API to detect app state

### SSE vs WebSockets

| Feature | SSE | WebSockets |
|---------|-----|------------|
| Direction | Server → Client only | Bidirectional |
| Protocol | HTTP | WS/WSS |
| Auto-reconnect | ✅ Built-in | ❌ Manual |
| Simplicity | ✅ Simple | ❌ Complex |
| Use Case | Live logs, notifications | Real-time chat, gaming |

**For this app, SSE is perfect** because:
- We only need server-to-client updates
- Automatic reconnection is valuable
- HTTP protocol works everywhere (no firewall issues)

---

## Proposed Mobile-First UI

### Design Principles

1. **Mobile-first**: Design for phones, scale up to tablets/desktop
2. **Progressive Web App (PWA)**: Installable, works offline for cached data
3. **Touch-optimized**: Large tap targets (minimum 44×44px)
4. **Fast & responsive**: Minimal JavaScript, lazy loading
5. **Accessible**: WCAG 2.1 AA compliant

### Recommended Layout

#### 1. Bottom Navigation (Mobile)
```
┌─────────────────────┐
│  Pocket Dev Guild   │ ← Header
├─────────────────────┤
│                     │
│   Main Content      │
│   (Tab-specific)    │
│                     │
│                     │
├─────────────────────┤
│ 🏠  💬  📝  ⚙️    │ ← Bottom Nav
│Repos Conv Jobs Sett │
└─────────────────────┘
```

#### 2. Sidebar Navigation (Desktop)
```
┌────────┬────────────────┐
│        │                │
│  Nav   │  Main Content  │
│ Panel  │                │
│        │                │
│        │                │
└────────┴────────────────┘
```

### Screen Breakdown

#### Screen 1: Repositories & Worktrees
**Mobile View**:
- Expandable card per repository
- Tap to expand → show worktrees list
- Floating Action Button (FAB) to create worktree
- **Swipe-to-delete** on worktree items (except primary)
- Pull-to-refresh

**Features**:
```
┌──────────────────────────┐
│ 📚 Repositories          │
│ ──────────────────────── │
│ ┌──────────────────────┐ │
│ │ 📦 my-project        │ │
│ │ /home/user/repos/... │ │
│ │ ▼ Worktrees (3)      │ │
│ │   ├─ main (primary)  │ │
│ │   ├─ feature_auth  🗑 │ │  ← swipe left to delete
│ │   └─ fix_bug-123   🗑 │ │
│ └──────────────────────┘ │
│                          │
│ ┌──────────────────────┐ │
│ │ 📦 another-project   │ │
│ │ ▶ Worktrees (1)      │ │
│ └──────────────────────┘ │
│                          │
│               [+ FAB]    │
└──────────────────────────┘
```

**Desktop View**:
- Delete button appears on hover
- Confirmation dialog before deletion

#### Screen 2: Conversations
**Mobile View**:
- List of conversations, newest first
- Group by repository (collapsible sections)
- Swipe actions: Archive, Delete
- Show last update time & summary
- FAB to create new conversation

**Features**:
```
┌──────────────────────────┐
│ 💬 Conversations         │
│ ──────────────────────── │
│ my-project               │
│ ┌──────────────────────┐ │
│ │ 🔵 Auth Implementation│ │
│ │ 3 turns · 2h ago     │ │
│ │ "Working on JWT..."  │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ ⚫ Fix Login Bug     │ │
│ │ 1 turn · 1d ago      │ │
│ │ "Fixed validation"   │ │
│ └──────────────────────┘ │
│                          │
│               [+ FAB]    │
└──────────────────────────┘

Legend:
🔵 = Active (has running turn)
⚫ = Idle
```

**Conversation Detail View**:
```
┌──────────────────────────┐
│ ← Auth Implementation    │
│ ──────────────────────── │
│ 📝 Summary               │
│ Working on JWT auth for  │
│ the API. Added models... │
│ ──────────────────────── │
│ 💬 Turns                 │
│ ┌──────────────────────┐ │
│ │ 1️⃣ "Add auth models" │ │
│ │    ✅ 2m ago          │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ 2️⃣ "Add unit tests"  │ │
│ │    ✅ 1h ago          │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ 3️⃣ "Fix failing..."  │ │
│ │    🔄 Running...      │ │
│ │    [View Logs]        │ │
│ └──────────────────────┘ │
│                          │
│ ┌────────────────────┐   │
│ │ Your prompt here...│   │
│ └────────────────────┘   │
│            [Send →]      │
└──────────────────────────┘
```

#### Screen 3: Jobs History
**Mobile View**:
- Job history with filters (status, repo, date, conversation)
- Live status indicators
- Tap to view logs
- Jobs are always part of a conversation

**Features**:
```
┌──────────────────────────┐
│ 📝 Jobs History          │
│ ──────────────────────── │
│ 🔍 [Filters: All ▼]      │
│ ──────────────────────── │
│ ┌──────────────────────┐ │
│ │ 🔄 Add unit tests    │ │
│ │ Conv: Auth Impl      │ │
│ │ my-project/feature   │ │
│ │ Running · 2m 15s     │ │
│ │ [View Logs]          │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ ✅ Fix bug #123      │ │
│ │ Conv: Bug Fixes      │ │
│ │ my-project/main      │ │
│ │ Finished · 5m ago    │ │
│ │ Exit: 0              │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ ❌ Refactor auth     │ │
│ │ Conv: Refactoring    │ │
│ │ another-project      │ │
│ │ Failed · 1h ago      │ │
│ │ Exit: 1              │ │
│ └──────────────────────┘ │
└──────────────────────────┘

Note: All jobs belong to a conversation.
Create jobs via conversation turns.
```

#### Screen 4: Job Log Viewer
**Mobile View**:
- Full-screen log output
- Auto-scroll to bottom (with manual override)
- Status bar showing job state
- Share/copy log actions

**Features**:
```
┌──────────────────────────┐
│ ← Job: Add unit tests    │
│ ──────────────────────── │
│ 🔄 Running · 3m 42s      │
│ ━━━━━━━━━━━━━━━━━━━━━━ │
│ ┌──────────────────────┐ │
│ │ [stdout] Starting... │ │
│ │ [stdout] Loading...  │ │
│ │ [stdout] Analyzing...│ │
│ │ [stderr] Warning:... │ │
│ │ [stdout] Creating... │ │
│ │ [stdout] Writing...  │ │
│ │ [stdout] Running...  │ │
│ │ ...                  │ │
│ │ ▼                    │ │
│ └──────────────────────┘ │
│                          │
│ [📋 Copy] [📤 Share]     │
└──────────────────────────┘
```

### Tech Stack: Vite + React + TypeScript

**Required Stack**:
- **Vite**: Fast build tool with HMR
- **React 18**: Component-based UI library
- **TypeScript**: Type safety
- **TanStack Query** (React Query): Server state management, caching, and synchronization
- **Tailwind CSS**: Utility-first CSS framework
- **Shadcn/ui**: High-quality, accessible React components built on Radix UI

**Additional Libraries**:
- **React Router**: Client-side routing
- **Zustand**: Lightweight client state management
- **ansi-to-react**: ANSI escape sequence rendering for logs
- **date-fns**: Date formatting and manipulation

**Setup**:
```bash
# Create Vite + React + TypeScript project
npm create vite@latest pocket-dev-guild-ui -- --template react-ts
cd pocket-dev-guild-ui

# Install dependencies
npm install
npm install @tanstack/react-query react-router-dom zustand
npm install -D tailwindcss postcss autoprefixer
npm install ansi-to-react date-fns

# Initialize Tailwind
npx tailwindcss init -p

# Install Shadcn/ui
npx shadcn-ui@latest init
```

### Mobile-Specific Features

#### 1. Progressive Web App (PWA)
```json
// manifest.json
{
  "name": "Pocket Dev Guild",
  "short_name": "DevGuild",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#ffffff",
  "theme_color": "#2563eb",
  "icons": [
    {
      "src": "/icon-192.png",
      "sizes": "192x192",
      "type": "image/png"
    },
    {
      "src": "/icon-512.png",
      "sizes": "512x512",
      "type": "image/png"
    }
  ]
}
```

#### 2. Offline Support
- Cache static assets with Service Worker
- Show cached conversations/jobs when offline
- Queue actions (create worktree, start job) for when back online
- Clear "offline" indicator

#### 3. Touch Gestures
- **Pull-to-refresh**: Reload repo/conversation list
- **Swipe**: Delete conversation, archive job
- **Long-press**: Quick actions menu
- **Pinch-to-zoom**: Scale log text

#### 4. Notifications
- Push notifications for job completion (requires backend)
- Vibration feedback on actions
- Badge count on app icon

---

## Implementation Recommendations

### 1. Generated TypeScript Client

Use OpenAPI generator to create a type-safe API client:

```bash
# Install generator
npm install -D openapi-typescript-codegen

# Generate client from OpenAPI spec
npx openapi-typescript-codegen --input http://localhost:8000/openapi.json \
                                --output ./src/api \
                                --client fetch
```

**Benefits**:
- Full TypeScript types for all endpoints
- Auto-completion in IDE
- Compile-time error checking
- No manual request/response typing

**Usage**:
```typescript
import { JobsService, ConversationsService } from './api';

// Fully typed!
const job = await JobsService.createJob({
  repo_id: 'my-project',
  worktree: 'feature_auth',
  prompt: 'Add unit tests',
  conversation_id: null
});

console.log(job.job_id); // Type: string
```

### 2. State Management with Zustand

Use **Zustand** for lightweight client state (UI state, selected repo, etc.) and **TanStack Query** for server state (API data).

```typescript
// stores/appStore.ts
import { create } from 'zustand';

interface AppState {
  selectedRepoId: string | null;
  selectedWorktree: string | null;
  selectedConversationId: string | null;
  setSelectedRepo: (repoId: string) => void;
  setSelectedWorktree: (worktree: string | null) => void;
  setSelectedConversation: (conversationId: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedRepoId: null,
  selectedWorktree: null,
  selectedConversationId: null,
  setSelectedRepo: (repoId) => set({ selectedRepoId: repoId }),
  setSelectedWorktree: (worktree) => set({ selectedWorktree: worktree }),
  setSelectedConversation: (conversationId) => set({ selectedConversationId: conversationId }),
}));
```

**TanStack Query** for server state:
```typescript
// hooks/useRepos.ts
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '../api/client';

export function useRepos() {
  return useQuery({
    queryKey: ['repos'],
    queryFn: () => apiClient.repos.list(),
  });
}

// hooks/useConversations.ts
export function useConversations(repoId?: string) {
  return useQuery({
    queryKey: ['conversations', repoId],
    queryFn: () => apiClient.conversations.list({ repo_id: repoId }),
    enabled: !!repoId,
  });
}
```

### 3. ANSI Escape Sequence Handling with ansi-to-react

Agent output contains ANSI color codes. Use **ansi-to-react** to render them properly:

```bash
npm install ansi-to-react
```

```typescript
// components/LogViewer.tsx
import Ansi from 'ansi-to-react';

interface LogViewerProps {
  logs: LogLine[];
}

export function LogViewer({ logs }: LogViewerProps) {
  return (
    <div className="bg-black text-white p-4 rounded font-mono text-sm overflow-auto max-h-[70vh]">
      {logs.map((log, idx) => (
        <div key={idx} className={log.stream === 'stderr' ? 'text-red-400' : ''}>
          <Ansi>{log.line}</Ansi>
        </div>
      ))}
    </div>
  );
}
```

**Benefits**:
- Preserves colors and formatting
- Properly escapes HTML to prevent XSS
- Works seamlessly with React
- Handles all ANSI escape sequences (colors, bold, etc.)

### 4. Error Handling with React Query

TanStack Query handles errors automatically with retry logic and error states:

```typescript
// hooks/useCreateJob.ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '../api/client';
import { toast } from 'sonner'; // or your preferred toast library

export function useCreateJob() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: JobCreate) => apiClient.jobs.create(data),
    onSuccess: (job) => {
      // Invalidate job list to refetch
      queryClient.invalidateQueries({ queryKey: ['jobs'] });
      toast.success(`Job ${job.job_id} started`);
    },
    onError: (error: Error) => {
      console.error('Failed to create job:', error);
      toast.error(`Failed to start job: ${error.message}`);
    },
  });
}

// Usage in component
function JobForm() {
  const createJob = useCreateJob();

  const handleSubmit = (data: JobCreate) => {
    createJob.mutate(data);
  };

  return (
    <div>
      {createJob.isPending && <Spinner />}
      {createJob.isError && <Alert variant="destructive">{createJob.error.message}</Alert>}
      {/* ... form ... */}
    </div>
  );
}
```

### 5. Performance Optimizations

#### React Query Caching
TanStack Query automatically caches and deduplicates requests:

```typescript
// Shared cache across components
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      gcTime: 1000 * 60 * 10,   // 10 minutes (formerly cacheTime)
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
```

#### Virtual Scrolling with react-window
For long logs (1000+ lines):

```bash
npm install react-window
```

```typescript
import { FixedSizeList } from 'react-window';

function LogViewer({ logs }: { logs: LogLine[] }) {
  const Row = ({ index, style }: { index: number; style: React.CSSProperties }) => (
    <div style={style} className="font-mono">
      <Ansi>{logs[index].line}</Ansi>
    </div>
  );

  return (
    <FixedSizeList
      height={600}
      itemCount={logs.length}
      itemSize={24}
      width="100%"
    >
      {Row}
    </FixedSizeList>
  );
}
```

#### Debounced Search with useDeferredValue
```typescript
import { useState, useDeferredValue } from 'react';

function SearchableList({ items }: { items: string[] }) {
  const [query, setQuery] = useState('');
  const deferredQuery = useDeferredValue(query);

  const filtered = items.filter(item =>
    item.toLowerCase().includes(deferredQuery.toLowerCase())
  );

  return (
    <div>
      <input value={query} onChange={e => setQuery(e.target.value)} />
      <ul>{filtered.map(item => <li key={item}>{item}</li>)}</ul>
    </div>
  );
}
```

### 6. Accessibility with Shadcn/ui

Shadcn/ui components are built on **Radix UI**, which provides accessible primitives out of the box:

```typescript
// components/ConversationList.tsx
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

function ConversationList({ conversations }: { conversations: ConversationInfo[] }) {
  return (
    <div>
      <Select aria-label="Select conversation">
        <SelectTrigger>
          <SelectValue placeholder="Select a conversation" />
        </SelectTrigger>
        <SelectContent>
          {conversations.map((conv) => (
            <SelectItem key={conv.id} value={conv.id}>
              {conv.title || conv.summary || conv.id.slice(0, 8)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Button variant="default" aria-label="Create new conversation">
        New Conversation
      </Button>
    </div>
  );
}
```

**Benefits of Radix UI / Shadcn**:
- Full keyboard navigation
- Screen reader support
- ARIA attributes automatically applied
- Focus management
- WCAG 2.1 AA compliant

### 7. Testing Strategy

#### Unit Tests with Vitest
```bash
npm install -D vitest @testing-library/react @testing-library/jest-dom
```

```typescript
// __tests__/ConversationList.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ConversationList } from '@/components/ConversationList';

describe('ConversationList', () => {
  it('renders conversations', () => {
    const conversations = [
      { id: '1', title: 'Test Conversation', /* ... */ },
    ];

    render(<ConversationList conversations={conversations} />);
    expect(screen.getByText('Test Conversation')).toBeInTheDocument();
  });
});
```

#### Component Tests with React Testing Library
```typescript
// __tests__/JobForm.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JobForm } from '@/components/JobForm';

it('creates a job on submit', async () => {
  const queryClient = new QueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <JobForm />
    </QueryClientProvider>
  );

  fireEvent.change(screen.getByLabelText('Prompt'), {
    target: { value: 'Run tests' },
  });
  fireEvent.click(screen.getByText('Start Job'));

  await waitFor(() => {
    expect(screen.getByText(/Job started/)).toBeInTheDocument();
  });
});
```

#### E2E Tests with Playwright
```bash
npm install -D @playwright/test
```

```typescript
// e2e/workflow.spec.ts
import { test, expect } from '@playwright/test';

test('create conversation and send turn', async ({ page }) => {
  await page.goto('http://localhost:5173');

  // Select repo
  await page.selectOption('[data-testid="repo-select"]', 'my-project');

  // Create conversation
  await page.fill('[data-testid="conversation-title"]', 'Test Conv');
  await page.click('[data-testid="create-conversation"]');

  // Send turn
  await page.fill('[data-testid="prompt"]', 'Add unit tests');
  await page.click('[data-testid="send-turn"]');

  // Verify log streaming
  await expect(page.locator('[data-testid="log-viewer"]')).toContainText('Starting');
});
```

---

## Security Considerations

### 1. Authentication (Future)
Currently, the app has **no authentication**. This is acceptable for `localhost` but **CRITICAL** for production.

**Planned solutions** (see `TODO.md`):
- Shared token (header/query param)
- OAuth2 proxy (Google, GitHub)
- Reverse proxy auth (Tailscale, Cloudflare Access)

**Frontend requirements**:
```javascript
// Add auth token to all requests
const token = localStorage.getItem('auth_token');

fetch('/jobs', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify(jobData)
});
```

### 2. CORS (Cross-Origin Resource Sharing)

If frontend is served from a different origin than the API:

```python
# Backend: app.py
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3. Input Validation with Zod

**Always validate user input** with Zod schemas:

```bash
npm install zod
```

```typescript
// lib/validation.ts
import { z } from 'zod';

export const branchNameSchema = z.string()
  .regex(/^[A-Za-z]+\/[A-Za-z0-9.-]+$/, {
    message: 'Branch must follow format: Kind/name (e.g., feature/auth, release/2.5.x)',
  });

export const worktreeNameSchema = z.string()
  .regex(/^[A-Za-z0-9_-]+$/, {
    message: 'Worktree name can only contain letters, numbers, - and _',
  });

export const jobCreateSchema = z.object({
  repo_id: worktreeNameSchema,
  worktree: worktreeNameSchema.nullable(),
  prompt: z.string().min(1, 'Prompt is required'),
  conversation_id: z.string().nullable().optional(),
});

// Usage in React Hook Form
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';

function WorktreeForm() {
  const form = useForm({
    resolver: zodResolver(z.object({ branch: branchNameSchema })),
  });

  const onSubmit = (data: { branch: string }) => {
    // data.branch is validated
    createWorktree.mutate(data);
  };

  return <form onSubmit={form.handleSubmit(onSubmit)}>{ /* ... */ }</form>;
}
```

### 4. XSS Prevention

**Never use `innerHTML` with untrusted content**:

```javascript
// ❌ VULNERABLE
logElement.innerHTML = logLine.line;

// ✅ SAFE (plain text)
logElement.textContent = logLine.line;

// ✅ SAFE (sanitized HTML for ANSI)
import DOMPurify from 'dompurify';
const clean = DOMPurify.sanitize(ansiToHtml(logLine.line));
logElement.innerHTML = clean;
```

### 5. Rate Limiting

Consider client-side rate limiting for API calls:

```javascript
class RateLimiter {
  constructor(maxRequests, perSeconds) {
    this.maxRequests = maxRequests;
    this.perSeconds = perSeconds;
    this.requests = [];
  }

  async throttle() {
    const now = Date.now();
    this.requests = this.requests.filter(
      t => t > now - this.perSeconds * 1000
    );

    if (this.requests.length >= this.maxRequests) {
      const oldestRequest = Math.min(...this.requests);
      const waitTime = (oldestRequest + this.perSeconds * 1000) - now;
      await new Promise(resolve => setTimeout(resolve, waitTime));
    }

    this.requests.push(Date.now());
  }
}

// Usage: max 10 job creations per minute
const jobLimiter = new RateLimiter(10, 60);

async function createJob(data) {
  await jobLimiter.throttle();
  return fetch('/jobs', { method: 'POST', body: JSON.stringify(data) });
}
```

---

## Getting Started Checklist

### Setup (Vite + React + TypeScript)
- [ ] Create Vite + React + TypeScript project
- [ ] Install dependencies (TanStack Query, React Router, Zustand, Tailwind, Shadcn/ui)
- [ ] Configure Tailwind CSS
- [ ] Initialize Shadcn/ui components
- [ ] Generate TypeScript types from OpenAPI spec
- [ ] Set up folder structure (components, hooks, api, lib, stores)

### Core Features
- [ ] Implement API client with generated types
- [ ] Set up TanStack Query and React Router
- [ ] Create Zustand store for client state
- [ ] Implement repository and worktree management with **delete UI**
- [ ] Build conversation list and detail views
- [ ] Implement job creation through conversation turns
- [ ] Add SSE log streaming with ansi-to-react
- [ ] Implement real-time conversation updates via SSE
- [ ] Add worktree deletion UI (swipe-to-delete on mobile, button on desktop)

### UI/UX
- [ ] Build mobile-first responsive layout (bottom nav on mobile, sidebar on desktop)
- [ ] Add error handling with toast notifications
- [ ] Implement loading states (skeletons, spinners)
- [ ] Add keyboard shortcuts
- [ ] Implement dark mode support
- [ ] Test on mobile devices (responsive, touch gestures)

### Polish & Deploy
- [ ] Add virtual scrolling for long logs (react-window)
- [ ] Write unit tests (Vitest + React Testing Library)
- [ ] Write E2E tests (Playwright)
- [ ] Implement PWA features (manifest, service worker, offline support)
- [ ] Optimize bundle size (lazy loading, code splitting)
- [ ] Set up CI/CD pipeline (GitHub Actions, Vercel, Netlify)
- [ ] Deploy to production

---

## Resources

### Documentation
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Server-Sent Events MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [PWA Guides](https://web.dev/progressive-web-apps/)

### Libraries
- [React](https://react.dev/)
- [Vite](https://vitejs.dev/)
- [TanStack Query](https://tanstack.com/query)
- [React Router](https://reactrouter.com/)
- [Zustand](https://zustand-demo.pmnd.rs/)
- [Tailwind CSS](https://tailwindcss.com/)
- [Shadcn/ui](https://ui.shadcn.com/)
- [Radix UI](https://www.radix-ui.com/)
- [ansi-to-react](https://github.com/nteract/ansi-to-react)
- [Zod](https://zod.dev/)
- [React Hook Form](https://react-hook-form.com/)
- [openapi-typescript-codegen](https://github.com/ferdikoomen/openapi-typescript-codegen)

### Tools
- [Vitest](https://vitest.dev/)
- [Playwright](https://playwright.dev/)
- [React Testing Library](https://testing-library.com/react)
- [Chrome DevTools](https://developer.chrome.com/docs/devtools/)
- [React DevTools](https://react.dev/learn/react-developer-tools)

---

## Contact & Support

For questions or contributions, please refer to the main repository documentation or open an issue on GitHub.

**Happy coding! 🚀**
