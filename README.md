# LLM Expert Group

A human-in-the-loop, repository-grounded expert council for technical and research decisions.

The project is intentionally **not** a "many LLMs vote and majority wins" system. A Chairman moderates the council and makes evaluative judgments. A separate Secretary performs factual, non-creative repository work. Experts reason independently and may privately ask the Secretary for implementation facts before committing to an opinion. After the Chairman synthesizes a round, execution pauses at a human-controlled gate.

## Workflow

```text
                         Human
                           |
                           v
                       Chairman
                  agenda / judgment
                           |
                    ask Secretary
                           |
                           v
                       Secretary
                factual repository QA
                           |
                    Neutral opening
                           |
               +-----------+-----------+
               v           v           v
            Expert A    Expert B    Expert N
               |           |           |
               +---- private ask_secretary ----+
               |           |           |
               v           v           v
             final independent opinions
                           |
                           v
                  Chairman synthesis
                  /                 \
          ask Secretary         evaluate debate
                  \                 /
                           v
                       HUMAN GATE
              +------------+-----------+------------+
              v            v           v            v
            STOP        CONTINUE    REDIRECT    INVESTIGATE
```

## Roles

### Chairman

The Chairman is the council moderator and evaluator. It prepares a neutral opening, extracts real disagreements, preserves minority arguments, judges evidence quality, and proposes the next agenda. It is allowed to recommend a direction, but should ask the Secretary instead of guessing about repository facts.

### Expert

Experts are independent analytical agents. During a round, they cannot see other experts' responses or Secretary conversations. Each expert can make several private `ask_secretary` requests before returning its final opinion.

### Secretary

The Secretary is deliberately non-creative. Its job is to answer questions such as "where is this implemented?", "what contract does this test enforce?", or "what changed in Git?" It has read-only tools for repository tree navigation, text search, file reads, Git log, and Git diff. It must not rank architectures or recommend what the project should do.

Secretary file/line citations are re-read and validated by the backend. A `VERIFIED` answer with no valid repository evidence is automatically downgraded.

### Human

The human owns the round boundary. The council cannot automatically debate until consensus. After the Chairman synthesis is streamed and persisted, the UI waits for one of four actions: `continue`, `redirect`, `investigate`, or `stop`.

## Streaming round runtime

Starting a round is intentionally a short request. The backend persists a `CouncilRoundRun`, executes it in the background, and exposes its durable event log over SSE.

1. Chairman opening is streamed to the UI.
2. Once complete, Experts begin in parallel and stream into independent UI cards.
3. After all Experts reach a terminal state, the Chairman synthesis streams.
4. The persisted Human Gate returns the session to `ready` or `stopped`.

SSE events are stored in SQLite, so reconnecting clients replay missed text from the event sequence instead of losing partial output.

## Design principles

- **Independent expert responses.** Experts see the Chairman's opening, not one another's answers.
- **Private factual queries.** Expert A cannot observe Expert B's Secretary questions during a round.
- **Neutral opening.** The Chairman is explicitly instructed not to reveal a preferred solution before experts answer.
- **Evidence over voting.** A minority position may dominate if its argument and evidence are stronger.
- **Facts and judgment are separate roles.** Secretary answers "what is true in the repository?"; Chairman/Experts answer "what should we conclude?"
- **Human controls the rounds.** There is no automatic "debate until consensus" loop.
- **Durable execution.** The application database persists run state, streamed events, final records, and provenance.
- **Provider-neutral model layer.** Every model independently configures endpoint, API key, model name, headers, parameters, and wire protocol.

## Supported model protocols

The backend uses raw HTTP rather than vendor SDKs so custom gateways work naturally.

- `openai_responses`: `POST .../v1/responses`, Bearer auth; uses `instructions` + `input`.
- `anthropic_messages`: `POST .../v1/messages`, `x-api-key` + `anthropic-version`; uses `system` + `messages`.
- `openai_chat_completions`: optional compatibility dialect for vendors/gateways that still expose `POST .../v1/chat/completions`.

The Chairman, Secretary, and every Expert may use a completely different provider, endpoint, API key, and protocol.

### Reasoning depth

Reasoning is a first-class per-model setting instead of a vendor-specific `params` guess:

```yaml
# OpenAI Responses (and OpenAI-compatible Chat Completions)
reasoning:
  effort: high

# Newer Claude models with adaptive thinking
reasoning:
  mode: adaptive
  effort: high

# Legacy Claude models with manual extended thinking
reasoning:
  mode: budget
  budget_tokens: 6000
```

The compatibility layer translates the normalized setting for each protocol:

- `openai_responses` -> `reasoning: {effort: ...}`;
- `openai_chat_completions` -> top-level `reasoning_effort`;
- `anthropic_messages` adaptive mode -> `thinking: {type: adaptive}` plus `output_config.effort`;
- `anthropic_messages` budget mode -> `thinking: {type: enabled, budget_tokens: ...}`.

`mode: disabled` explicitly asks the provider to disable reasoning where that model supports it. Omitting `reasoning` preserves the provider/model default. `params` is still applied last, so a custom gateway can override any normalized mapping with its exact raw payload fields. Unsupported combinations fail before the HTTP request rather than being silently ignored.

## Quick start

### 1. Configure models

```bash
cp config.example.yaml config.yaml
```

Create a `.env` file next to `config.yaml` and put the API keys there. The backend loads it automatically at startup, while preserving any values explicitly set in the process environment:

```bash
CHAIRMAN_API_KEY=...
SECRETARY_API_KEY=...
GPT_EXPERT_API_KEY=...
CLAUDE_EXPERT_API_KEY=...
THIRD_PARTY_API_KEY=...
```

The core role configuration is:

```yaml
chairman: chairman
secretary: secretary
experts:
  - gpt-expert
  - claude-expert

actor_max_secretary_queries: 4
secretary_max_tool_steps: 8
# The Chairman receives a larger evidence budget before producing an opening.
chairman_opening_max_secretary_queries: 12
chairman_opening_secretary_max_tool_steps: 24
chairman_synthesis_max_secretary_queries: 8
chairman_synthesis_secretary_max_tool_steps: 16
```

Role IDs reference entries in `models`. The same underlying model may be configured for more than one role, although using a cheaper factual model for Secretary is often reasonable.

### 2. Run backend

```bash
make backend-install  # only needed once, or after dependency changes
make backend-dev
```

The backend exposes OpenAPI docs at `http://127.0.0.1:8000/docs`.

### 3. Run frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

### 4. Start a council session

Enter:

- a session title;
- a repository path visible to the backend process, such as `/home/user/src/syncfuzz`;
- the technical/research question.

The session records the initial Git commit and a bounded repository snapshot for provenance. During discussion, the Secretary reads the repository through a read-only workspace and every Secretary interaction records the commit observed at query time.

## Secretary provenance

Each Secretary interaction records:

- requester role and model ID;
- phase (`opening`, `expert`, or `synthesis`);
- exact factual question;
- factual answer and verification status;
- validated file/line evidence excerpts;
- limitations;
- repository tool trace;
- Git commit observed at query time.

The React UI exposes these interactions underneath the Chairman and each Expert so a recommendation can be audited back to the facts it consulted.

## Human actions

After each Chairman synthesis, the persisted round enters `awaiting_human`.

- **Continue** — close the current round and allow the next round to narrow unresolved disagreements.
- **Redirect** — requires a note; the next opening follows the new human focus.
- **Investigate** — requires a note; the next round focuses on disputed factual claims and evidence acquisition.
- **Stop** — permanently close the session.

Resuming a Human Gate does **not** automatically start another model round. The UI returns to `ready`, keeping the human in control of when the next round actually runs.

## API surface

- `GET /api/models` — redacted role/model configuration.
- `GET /api/sessions` — session history.
- `POST /api/sessions` — capture repository metadata and create a council.
- `POST /api/sessions/{id}/rounds` — create a background round run and return `202 Accepted`.
- `GET /api/round-runs/{id}/events` — durable SSE stream for Chairman, Expert, synthesis, and failure events.
- `GET /api/round-runs/{id}` — current run state.
- `POST /api/sessions/{id}/action` — record `continue`, `redirect`, `investigate`, or `stop` after the Human Gate.

## Persistence

The application database (`database_url`) stores sessions, in-flight runs, event sequences, final rounds, expert responses, Chairman output, human actions, and normalized Secretary provenance.

## Security notes

- Keep API keys in environment variables; `config.yaml` is ignored by Git.
- The Secretary has read-only repository tools; there is no repository write or shell execution tool in v0.2.
- Experts do not receive the raw repository. They receive the Chairman opening and only factual answers they explicitly request from their private Secretary interaction.
- The Chairman also obtains implementation facts through Secretary queries rather than receiving a giant raw repository prompt.
- Treat repository content as potentially sensitive input and configure providers accordingly.
- For OpenAI Responses, the example config uses `store: false` where supported.

## Development

Backend tests:

```bash
cd backend
pytest
```

Frontend production build:

```bash
cd frontend
npm install
npm run build
```

## Roadmap

1. Stream Secretary tool progress alongside actor text.
2. Resume an interrupted model call safely after process restart (current behavior marks it failed and retryable rather than replaying a potentially billable request).
3. Replay/fork from a recorded round with alternate models or human edits.
4. Tool-using Investigator role for tests, shell commands, web research, GitHub, or MCP under an explicit permission boundary.
5. Repository refresh/diff policies between rounds.
6. Exportable decision report and machine-readable session bundle.
