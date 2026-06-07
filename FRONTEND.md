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
- **Size**: ~130 lines of vanilla JavaScript
- **Features**:
  - Repository selection dropdown
  - Worktree management (list, create)
  - Single job submission
  - Real-time log streaming via SSE
- **Limitations**:
  - No conversation support
  - No job history
  - No mobile optimization
  - Basic UI with minimal styling

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

**Request Body**:
```json
{
  "branch": "feature/new-feature"
}
```

**Response**: `200 OK`
```json
{
  "name": "feature_new-feature",
  "path": "/home/user/repos/my-project-worktrees/feature_new-feature"
}
```

**Notes**:
- Branch name must follow pattern: `^[a-z]+(/[a-z0-9-]+)+$`
- Worktree directory name is derived by replacing `/` with `_`
- Automatically branches from the default remote branch (usually `origin/main`)

##### `DELETE /repos/{repo_id}/worktrees/{name}`
Remove a worktree.

**Response**: `200 OK`
```json
{
  "removed": "feature_new-feature"
}
```

#### Jobs

##### `POST /jobs`
Start a new job (agent run).

**Request Body**:
```json
{
  "repo_id": "my-project",
  "worktree": "feature_new-feature",
  "prompt": "Add unit tests for the authentication module",
  "conversation_id": null
}
```

**Response**: `200 OK`
```json
{
  "job_id": "a1b2c3d4e5f6..."
}
```

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
List all conversations with optional filtering.

**Query Parameters**:
- `repo_id` (optional): Filter by repository

**Response**: `200 OK`
```json
[
  {
    "id": "conv-abc123...",
    "repo_id": "my-project",
    "worktree": "feature_new-feature",
    "agent_id": null,
    "title": "Implement authentication",
    "session_id": "session-xyz...",
    "summary": "Working on adding JWT authentication to the API",
    "created_at": "2026-06-07T10:00:00Z",
    "updated_at": "2026-06-07T10:45:00Z",
    "turns": ["job-1", "job-2", "job-3"]
  }
]
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
  branch: string;             // Matches ^[a-z]+(/[a-z0-9-]+)+$
}

interface WorktreeCreated {
  name: string;
  path: string;
}

// Jobs
type JobStatus = 'queued' | 'running' | 'finished' | 'failed';
type LogStream = 'stdout' | 'stderr';

interface JobCreate {
  repo_id: string;
  worktree: string | null;    // null = use primary checkout
  prompt: string;
  conversation_id: string | null;
}

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
  created_at: string;         // ISO 8601
  updated_at: string;         // ISO 8601
  turns: string[];            // Array of job IDs
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
│ │   ├─ feature_auth    │ │
│ │   └─ fix_bug-123     │ │
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

#### Screen 3: Jobs (Standalone)
**Mobile View**:
- Quick job creation without conversation
- Job history with filters (status, repo, date)
- Live status indicators
- Tap to view logs

**Features**:
```
┌──────────────────────────┐
│ 📝 Jobs                  │
│ ──────────────────────── │
│ 🔍 [Filters: All ▼]      │
│ ──────────────────────── │
│ ┌──────────────────────┐ │
│ │ 🔄 Add unit tests    │ │
│ │ my-project/feature   │ │
│ │ Running · 2m 15s     │ │
│ │ [View Logs]          │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ ✅ Fix bug #123      │ │
│ │ my-project/main      │ │
│ │ Finished · 5m ago    │ │
│ │ Exit: 0              │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │
│ │ ❌ Refactor auth     │ │
│ │ another-project      │ │
│ │ Failed · 1h ago      │ │
│ │ Exit: 1              │ │
│ └──────────────────────┘ │
│                          │
│     [Start Quick Job]    │
└──────────────────────────┘
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

### Component Library Recommendations

#### Option 1: Minimal (Vanilla + Tailwind CSS)
- **Tailwind CSS**: Utility-first CSS framework
- **Alpine.js** (optional): Lightweight reactivity
- **No build step** required with CDN
- **Pros**: Fast, small bundle, easy to learn
- **Cons**: Manual state management

```html
<!-- Example with Tailwind + Alpine -->
<div x-data="{ open: false }">
  <button @click="open = !open"
          class="bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded">
    Toggle
  </button>
  <div x-show="open" class="mt-2 p-4 bg-gray-100 rounded">
    Content
  </div>
</div>
```

#### Option 2: Modern SPA (Vite + Svelte)
- **Vite**: Fast build tool
- **Svelte**: Compile-time framework (small runtime)
- **TypeScript**: Type safety
- **Pros**: Component-based, reactive, great DX
- **Cons**: Build step required

```svelte
<!-- Example Svelte component -->
<script lang="ts">
  let count = 0;
  $: doubled = count * 2;
</script>

<button on:click={() => count++}>
  Count: {count} (doubled: {doubled})
</button>
```

#### Option 3: React Ecosystem (Vite + React)
- **Vite + React**: Industry standard
- **React Query**: Server state management
- **Tailwind CSS**: Styling
- **Pros**: Large ecosystem, familiar to many
- **Cons**: Larger bundle size

**Recommendation**: Start with **Option 1** for MVP, migrate to **Option 2** (Svelte) if complexity grows.

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

### 2. State Management

#### For Vanilla JS (Simple)
Use a simple reactive store:

```javascript
// store.js
class Store {
  constructor(initialState = {}) {
    this.state = initialState;
    this.listeners = [];
  }

  getState() {
    return this.state;
  }

  setState(newState) {
    this.state = { ...this.state, ...newState };
    this.listeners.forEach(listener => listener(this.state));
  }

  subscribe(listener) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }
}

// Usage
const store = new Store({ repos: [], jobs: [] });

store.subscribe((state) => {
  console.log('State updated:', state);
  renderUI(state);
});

store.setState({ repos: [{ id: '1', name: 'Project' }] });
```

#### For Svelte (Built-in)
Svelte has built-in reactivity, no external store needed:

```svelte
<script lang="ts">
  import { writable } from 'svelte/store';

  const jobs = writable<JobInfo[]>([]);

  // Subscribe to changes
  jobs.subscribe(value => {
    console.log('Jobs updated:', value);
  });

  // Update store
  jobs.update(j => [...j, newJob]);
</script>
```

### 3. ANSI Escape Sequence Handling

Agent output contains ANSI color codes. Three options:

#### Option A: Strip on Server (Simplest)
Modify `SubprocessAugmentRunner._pump` to remove ANSI codes:

```python
import re

ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')

async def _pump(self, stream, stream_name):
    async for line_bytes in stream:
        line = line_bytes.decode('utf-8', errors='replace')
        # Remove ANSI codes
        line = ANSI_ESCAPE.sub('', line)
        await self._store.append_log(self._job_id, stream_name, line)
```

#### Option B: Render in Browser (Best UX)
Use a library like `ansi-to-html`:

```bash
npm install ansi-to-html
```

```javascript
import AnsiToHtml from 'ansi-to-html';

const convert = new AnsiToHtml({
  fg: '#FFF',
  bg: '#000',
  newline: true,
  escapeXML: true
});

// Convert ANSI to HTML
const html = convert.toHtml(logLine.line);
logElement.innerHTML += html;
```

**Recommendation**: Use **Option B** for production (preserves colors), **Option A** for quick MVP.

### 4. Error Handling

```typescript
// API wrapper with error handling
async function apiCall<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch (error) {
    if (error instanceof Response) {
      const text = await error.text();
      console.error(`API Error ${error.status}:`, text);

      // Show user-friendly message
      if (error.status === 404) {
        showToast('Resource not found');
      } else if (error.status === 409) {
        showToast('Conflict: ' + text);
      } else {
        showToast('Request failed: ' + text);
      }
    } else {
      console.error('Network error:', error);
      showToast('Network error. Check connection.');
    }
    return null;
  }
}

// Usage
const job = await apiCall(() =>
  JobsService.createJob({ repo_id, worktree, prompt })
);
if (job) {
  navigateToJobLog(job.job_id);
}
```

### 5. Performance Optimizations

#### Lazy Loading
```javascript
// Load job logs only when needed
async function openJobDetail(jobId) {
  showLoadingSpinner();

  const [job, log] = await Promise.all([
    fetch(`/jobs/${jobId}`).then(r => r.json()),
    fetch(`/jobs/${jobId}/log`).then(r => r.json())
  ]);

  hideLoadingSpinner();
  renderJobDetail(job, log);
}
```

#### Virtual Scrolling
For long logs (1000+ lines), use virtual scrolling:

```bash
npm install react-window  # or svelte-virtual-list
```

```javascript
// Only render visible log lines
import { FixedSizeList } from 'react-window';

<FixedSizeList
  height={600}
  itemCount={logLines.length}
  itemSize={24}
  width="100%"
>
  {({ index, style }) => (
    <div style={style}>{logLines[index]}</div>
  )}
</FixedSizeList>
```

#### Debounce Search
```javascript
function debounce(fn, delay) {
  let timeoutId;
  return function(...args) {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(...args), delay);
  };
}

// Usage for search input
const searchJobs = debounce((query) => {
  // Perform search
  const results = jobs.filter(j =>
    j.prompt.toLowerCase().includes(query.toLowerCase())
  );
  renderResults(results);
}, 300);
```

### 6. Accessibility (a11y)

```html
<!-- Semantic HTML -->
<nav aria-label="Main navigation">
  <button aria-label="Repositories" aria-current="page">
    <span aria-hidden="true">🏠</span>
    <span>Repos</span>
  </button>
</nav>

<!-- Keyboard navigation -->
<div role="listbox" aria-label="Worktrees">
  <div role="option" tabindex="0" aria-selected="false">
    feature/new-ui
  </div>
</div>

<!-- Screen reader announcements -->
<div role="status" aria-live="polite" aria-atomic="true">
  Job started successfully
</div>

<!-- Loading states -->
<button aria-busy="true" disabled>
  <span class="spinner" aria-hidden="true"></span>
  Loading...
</button>
```

### 7. Testing Strategy

#### Unit Tests
```javascript
// Test API client
describe('JobsService', () => {
  it('creates a job', async () => {
    const job = await JobsService.createJob({
      repo_id: 'test',
      worktree: null,
      prompt: 'test prompt',
      conversation_id: null
    });
    expect(job.job_id).toBeTruthy();
  });
});
```

#### Integration Tests
```javascript
// Test SSE handling
describe('Job log streaming', () => {
  it('receives log events', (done) => {
    const es = new EventSource('/jobs/test-123/events');
    const logs = [];

    es.addEventListener('log', (e) => {
      logs.push(JSON.parse(e.data));
    });

    es.addEventListener('status', (e) => {
      expect(logs.length).toBeGreaterThan(0);
      es.close();
      done();
    });
  });
});
```

#### E2E Tests (Playwright)
```javascript
// Test full workflow
test('create worktree and start job', async ({ page }) => {
  await page.goto('http://localhost:8000');

  // Select repo
  await page.selectOption('#repo', 'my-project');

  // Create worktree
  await page.fill('#new-worktree', 'feature/test');
  await page.click('#create-worktree');

  // Wait for worktree to appear
  await page.waitForSelector('option:has-text("feature_test")');

  // Start job
  await page.fill('#prompt', 'Run tests');
  await page.click('#run');

  // Verify log appears
  await page.waitForSelector('#log:has-text("Starting")');
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

### 3. Input Validation

**Always validate user input** before sending to API:

```javascript
function validateBranchName(branch) {
  const pattern = /^[a-z]+\/[a-z0-9-]+$/;
  if (!pattern.test(branch)) {
    throw new Error('Branch must follow format: kind/name (e.g., feature/auth)');
  }
  return branch;
}

function validateWorktreeName(name) {
  const pattern = /^[A-Za-z0-9_-]+$/;
  if (!pattern.test(name)) {
    throw new Error('Worktree name can only contain letters, numbers, - and _');
  }
  return name;
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

### MVP (Vanilla JS + Tailwind)
- [ ] Set up Tailwind CSS via CDN or npm
- [ ] Generate TypeScript types from OpenAPI
- [ ] Create basic HTML structure with bottom navigation
- [ ] Implement repo/worktree listing
- [ ] Implement job creation and log streaming
- [ ] Add basic error handling and loading states
- [ ] Test on mobile device (Chrome DevTools device mode)
- [ ] Add PWA manifest and service worker
- [ ] Deploy to static host (Netlify, Vercel, GitHub Pages)

### Enhanced (Svelte + Vite)
- [ ] Set up Vite + Svelte + TypeScript
- [ ] Generate API client with `openapi-typescript-codegen`
- [ ] Create component library (Button, Card, List, etc.)
- [ ] Implement all screens (repos, conversations, jobs, settings)
- [ ] Add SSE reconnection logic
- [ ] Implement ANSI-to-HTML log rendering
- [ ] Add virtual scrolling for long logs
- [ ] Implement offline support with service worker
- [ ] Add push notifications (requires backend changes)
- [ ] Write unit + integration + E2E tests
- [ ] Optimize bundle size (code splitting, lazy loading)
- [ ] Deploy with CI/CD pipeline

---

## Resources

### Documentation
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Server-Sent Events MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [PWA Guides](https://web.dev/progressive-web-apps/)

### Libraries
- [Tailwind CSS](https://tailwindcss.com/)
- [Alpine.js](https://alpinejs.dev/)
- [Svelte](https://svelte.dev/)
- [openapi-typescript-codegen](https://github.com/ferdikoomen/openapi-typescript-codegen)
- [ansi-to-html](https://github.com/rburns/ansi-to-html)
- [DOMPurify](https://github.com/cure53/DOMPurify)

### Tools
- [Vite](https://vitejs.dev/)
- [Playwright](https://playwright.dev/)
- [Chrome DevTools](https://developer.chrome.com/docs/devtools/)

---

## Contact & Support

For questions or contributions, please refer to the main repository documentation or open an issue on GitHub.

**Happy coding! 🚀**
