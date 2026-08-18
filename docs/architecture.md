# Architecture

## Runtime split

LLM Expert Group deliberately separates orchestration, domain persistence, model transport, and repository access.

```text
React UI
   |
FastAPI
   |
CouncilOrchestrator
   |
   +---------------- SQLAlchemy ----------------> council.db
   |                  canonical audit record
   |
   +---------------- LangGraph -----------------> langgraph-checkpoints.sqlite
                      execution/checkpoint state
                              |
             +----------------+----------------+
             |                |                |
         Chairman         Expert workers    Human interrupt
             |                |
             +-------- ask_secretary --------+
                              |
                         Secretary graph
                              |
                  read-only RepositoryWorkspace
```

LangGraph does not own provider integrations. All LLM calls still go through `ModelAdapter.generate(system, prompt) -> text`.

## Top-level Council graph

The top-level graph is a `StateGraph`:

```text
START
  |
chairman_open
  |
  +---- Send(expert_worker, expert A) ----+
  +---- Send(expert_worker, expert B) ----+--> chairman_synthesize
  +---- Send(expert_worker, expert N) ----+            |
                                                       v
                                                   human_gate
                                                       |
                                                   interrupt()
                                                       |
                                                      END
```

`expert_results` and `secretary_interactions` use reducers because multiple expert workers update them concurrently.

A successful round is checkpointed under a unique LangGraph `thread_id`. The ID is persisted on the application `CouncilRound`. A new execution attempt receives a new thread ID so stale partial state from a failed attempt cannot contaminate a retry.

## Human Gate semantics

`human_gate` uses LangGraph's dynamic `interrupt()` rather than an application-only status flag.

`POST /api/sessions/{id}/action` resumes the paused graph with `Command(resume=...)`. The graph reaches `END`, after which SQLAlchemy records the human action. For `continue`, `redirect`, and `investigate`, the session returns to `ready`; starting the next round remains a separate human-triggered operation.

This gives real durable pause/resume semantics without turning "Continue" into an automatic debate loop.

## Chairman

The Chairman remains a single continuous role rather than being split into context and judge models.

Two phases use the same role:

1. **Opening** — create a neutral agenda without revealing a preferred solution.
2. **Synthesis** — compare expert arguments, preserve minority positions, distinguish evidence from assumption, recommend a direction, and propose the next agenda.

When repository facts matter, the Chairman has one capability: `ask_secretary`.

## Expert actor subgraph

Each Expert is an isolated LangGraph actor loop:

```text
actor model
   |
   +-- final ----------------------> END
   |
   +-- ask_secretary
            |
         Secretary
            |
      factual answer
            |
         actor model
```

The application-level JSON protocol is intentionally provider-neutral. It does not depend on OpenAI tool-call objects, Anthropic tool-use objects, or any vendor SDK.

Experts receive independent subgraph state. Expert A's Secretary transcript is never injected into Expert B's state.

## Secretary graph

The Secretary is non-normative and read-only.

```text
Secretary model
     |
     +-- tree ------+
     +-- search ----+
     +-- read ------+--> repository tool --> Secretary model
     +-- git_log ---+
     +-- git_diff --+
     |
     +-- answer -------------------------------> END
```

The Secretary system prompt explicitly prohibits architecture recommendations and undocumented project-intent inference.

### Evidence validation

The Secretary may propose citations, but the backend does not trust generated line references blindly. Every citation is re-read through `RepositoryWorkspace.evidence_excerpt()`.

Statuses are:

- `VERIFIED`
- `PARTIALLY_VERIFIED`
- `NOT_FOUND`
- `CONFLICTING_EVIDENCE`
- `UNSTRUCTURED`

A claimed `VERIFIED` result with zero valid citations is automatically downgraded to `PARTIALLY_VERIFIED`.

## RepositoryWorkspace

Secretary tools are bounded and read-only:

- `list_tree`
- `search`
- `read`
- `git_log`
- `git_diff`

Path resolution prevents traversal outside the configured repository root and rejects excluded directories. Reads and search obey configured file-size/suffix limits.

There is intentionally no write, shell, network, or test-execution tool in the Secretary role.

## Provider adapter layer

`ModelAdapter.generate(system, prompt) -> text` remains the only model interface consumed by LangGraph nodes.

Adapters own:

- endpoint normalization;
- authentication headers;
- request wire format;
- response text extraction.

Supported protocols:

- OpenAI Responses
- Anthropic Messages
- OpenAI-compatible Chat Completions

This keeps LangGraph replaceable and prevents orchestration code from becoming coupled to LangChain model abstractions.

## Persistence model

### Application database

`CouncilSession`

- repository path
- initial repository commit
- initial bounded snapshot/provenance
- status
- current round

`CouncilRound`

- round number and kind
- LangGraph thread ID
- Chairman opening
- all expert results, including provider failures
- Chairman synthesis
- human action and note

`SecretaryInteractionRow`

- requester role/model
- phase and sequence
- question and factual answer
- verification status
- validated evidence JSON
- limitations
- repository tool trace
- observed Git commit

### LangGraph checkpoint database

The checkpoint database stores runtime state needed for:

- durable Human Gate interrupts;
- resume after human input;
- future checkpoint inspection;
- future replay/fork/time-travel operations.

It is intentionally separate from the application audit database.

## Failure behavior

- One Expert failure is captured in that Expert branch and does not abort the whole fan-out.
- If every Expert fails, Chairman synthesis raises and the round enters application status `error`.
- Chairman failure aborts the round.
- A failed attempt does not advance `current_round` and its LangGraph thread is never reused for a fresh retry.
- Human action is not written to SQLAlchemy until the matching LangGraph interrupt successfully resumes.

## Future Investigator boundary

Secretary answers "what does the repository currently establish?"

A future Investigator will answer "what experiment can we perform to learn something new?" It may receive controlled shell/test/web/GitHub/MCP tools, but those permissions should be explicit and separately audited rather than silently expanding Secretary authority.
