# Running multiple instances behind a load balancer

TL;DR — in the current architecture, **broken on several levels**. MongoDB
makes job/conversation state persistent, but three critical things are
still **process-local**.

## What's process-local today

| Component | Where state lives | Problem with 2+ instances |
|---|---|---|
| `subprocess` (auggie) | Inside the Python process of the instance that received `POST /jobs` | Only that one instance pumps logs into Mongo. If it dies, logs stop; no peer knows there's anything to take over. |
| `NotificationHub` | In-memory `asyncio.Event` map, per instance | SSE on instance B blocks in `wait_for_update` because instance A's `notify` fires locally. The polling loop in `stream_job_events` still calls `store.get`, so status changes are seen with ≤5 s latency — but **new log lines** are polled every 5 s instead of pushed instantly. |
| `run_conversation_turn` task | `asyncio.create_task` on the instance that received `POST /jobs` | If that instance crashes, the conversation stays in `is_busy`, no session discovery, no summary. |
| `fail_orphans()` at startup | Looks at `status ∈ {queued, running}` without knowing which instance owns the job | **Kills jobs that are happily running on a peer instance.** |

## Scenarios

### 1. LB routes follow-up requests to a different instance

- `POST /jobs` → instance A → spawns subprocess A.
- `GET /jobs/{id}/events` → LB → instance B → SSE loop polls Mongo every 5 s
  (because `wait_for_update` never fires). **Works**, just slow and CPU-hungry.
- `POST /conversations/{id}/turns` while the job is running → LB → instance B
  → `is_busy(conversation_id)` reads the `conversations` collection (Mongo) →
  sees the last turn `status=running` → **409, correct**. ✅
- But session discovery + summary run in a task on A. If A crashes before the
  job finishes, no backfill happens — **even if auggie itself runs to completion**.

### 2. Sticky sessions / affinity

If the LB uses cookies / IP hash and always hits the same instance: logs +
SSE + orchestrator are all colocated, **behaves like a single instance**.
Until the sticky instance crashes — then the next request lands on B, which
sees the job state in Mongo but can't drive the subprocess.

### 3. Both instances start at the same time (e.g. deploy)

Both call `fail_orphans()` in parallel. Race: A marks job X as failed → B
sees X already failed (no match for `$in: [queued, running]`). Idempotent,
at least. ✅

### 4. Rolling deploy

- A has a job running, `status=running` in Mongo.
- B restarts → `fail_orphans()` → **marks the job owned by A as failed (-2)**.
- A keeps pumping logs into Mongo, eventually calls
  `set_status("finished", returncode=0)` → **overwrites the failed state**.
  Inconsistency: the job was "failed" for a window, then "finished"; the
  user sees the race in the SSE stream.
- Worse: the conversation orchestrator on A calls `append_turn` for the next
  turn — on a job B considered failed. Garbage data.

### 5. A crashes, B takes over nothing

No heartbeat → B has no way to know A is gone. The job on A stays `running`
in Mongo until some other restart triggers `fail_orphans`. With continuously
running instances: **the zombie window is unbounded**.

## What real multi-instance support would need

Roughly in order of effort:

1. **Owner id per job.** Add `instance_id` (UUID per process start) to job
   docs. `fail_orphans()` then runs with
   `instance_id == self.instance_id AND status in (...)` — only reaps *our*
   corpses.

2. **Heartbeat table.** Each instance writes
   `instances[id] = {last_seen: now}` every ~5 s. A lease reaper (running on
   some instance, locked via `findOneAndUpdate`) finds `instance_id`s without
   a fresh heartbeat and fails their jobs. Only then is "A is dead"
   centrally observable.

3. **Notifications via Mongo change streams** instead of in-process
   `NotificationHub`. Motor supports `db.jobs.watch(...)`. Each instance
   subscribes to `update` events for the jobs it cares about. Gives
   real-time SSE across instances.

4. **Job-pickup pattern.** `POST /jobs` only writes `status=queued` to Mongo.
   A worker pool on each instance polls/watches queued jobs and claims via
   `findOneAndUpdate({status:queued}, {$set:{status:running, instance_id:me}}, returnDocument:before)`.
   Only the successful claimer spawns the subprocess. Job ownership becomes
   decoupled from HTTP routing.

5. **Conversation orchestrator as a persistent state machine** instead of
   `asyncio.create_task`. Today, "after the job finishes: discover_session +
   summary" is an in-process continuation. It would have to be modelled as a
   second queued phase in the job lifecycle so any instance can pick up the
   follow-up.

6. **LB-side: sticky sessions** as a short-term workaround, plus a
   `/healthz` probe so the LB removes dead instances. Doesn't solve (1) or
   (4) though — if the sticky instance dies, its jobs are still zombies.

## Pragmatic path

If real HA isn't a goal: **stay single-instance.** With the current
`fail_orphans` hook, single-instance restarts are clean. Put the LB in
front only for TLS termination / routing, not for scale-out.

If HA is wanted: step 1 (`instance_id`) + step 2 (heartbeat) are the
minimum. Without those, running a second instance is actively dangerous,
not just inefficient.
