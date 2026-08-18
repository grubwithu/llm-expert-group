# Streaming round architecture

## Purpose

A council round may require many slow model calls: a Chairman opening, optional Secretary loops, independent Experts, and a Chairman synthesis. It must not be held inside one browser request.

The backend therefore treats a round as a durable background run. The browser starts it quickly, then receives the visible work as a replayable Server-Sent Events (SSE) stream.

```text
React UI                         FastAPI + worker                    SQLite
   | POST /rounds                     |                                |
   |--------------------------------->| create CouncilRoundRun         |
   | <------------------------------  | 202 + run id                   |
   |                                  |                                |
   | GET /round-runs/{id}/events      |                                |
   |=================================>| append/replay CouncilRoundEvent|
   |                                  |                                |
   | chairman text  <-----------------| Chairman actor                 |
   | experts text    <----------------| parallel Expert actors         |
   | synthesis text  <----------------| Chairman actor                 |
   | human_gate      <----------------| persist CouncilRound           |
```

## Phase order

1. `chairman.started` / `chairman.delta` / `chairman.completed`
2. After the opening completes, all `expert.started` workers begin in parallel. Each produces `expert.delta`, then `expert.completed` or `expert.failed`.
3. Once every Expert is terminal, a successful Expert set triggers `synthesis.started`, `synthesis.delta`, and `synthesis.completed`.
4. The completed round is persisted, session status becomes `awaiting_human`, and `human_gate` is emitted.

One Expert failing does not stop other Experts. If every Expert fails, the run enters `failed` and emits `round.failed` with per-provider error detail.

If synthesis fails after Experts complete, the run still retains the opening, every completed Expert response, and all prior stream events. The UI reconnects to that failed run and shows the partial council rather than hiding it behind the terminal error.

## HTTP surface

- `POST /api/sessions/{session_id}/rounds` creates a run and returns `202 Accepted` with `RoundRunOut`.
- `GET /api/round-runs/{run_id}` returns durable run state.
- `GET /api/sessions/{session_id}/round-runs/latest` lets a reloaded page reconnect to an active run.
- `GET /api/round-runs/{run_id}/events?after=N` replays events after sequence `N` and then follows new events over SSE.
- `POST /api/sessions/{session_id}/action` closes a persisted Human Gate. It never starts another model round automatically.

The former synchronous `/rounds/run` endpoint returns `410 Gone` so clients cannot accidentally create a request-bound long-running operation.

## Durable data

`CouncilRoundRun` is created before work starts. It holds run status, complete text accumulated at phase boundaries, serialized Expert results, and terminal error information.

`CouncilRoundEvent` stores monotonically ordered events per run. Token deltas are events, so a disconnected browser can rebuild the visible Chairman, Expert, and synthesis text without relying on in-memory queues.

After a successful synthesis, the application persists the existing canonical `CouncilRound` and normalized Secretary provenance records. The Human Gate acts on that canonical round.

## Model streaming

`ModelAdapter.stream(system, prompt)` yields text fragments. Native adapters use the provider streaming dialect:

- OpenAI Responses: `response.output_text.delta`
- Anthropic Messages: `content_block_delta`
- OpenAI-compatible Chat Completions: `choices[].delta.content`

The council protocol still asks actors for JSON actions (`ask_secretary` or `final`). The actor streams only the `final.content` JSON string to the UI; a private Secretary request does not leak protocol JSON to the audience.

Instead, an actor emits a structured `*.secretary.started` / `*.secretary.completed` event. The UI presents this as an "Asking Secretary…" research state.

## Secretary boundary

The Secretary retains read-only repository tools (`tree`, `search`, `read`, `git_log`, `git_diff`) and bounded iteration. Chairman and Expert Secretary conversations remain private. Citations are validated by reopening the cited repository lines before persistence.

## Current recovery boundary

Events and partial run state are durable, so an SSE reconnect is safe. On backend startup, a previously `queued` or `running` round is marked `failed` with a durable event and can be retried. The system deliberately does not silently replay a potentially billable model request.
