# LLM Expert Group

A human-in-the-loop, repository-grounded expert council for technical and research decisions.

The project is intentionally **not** a "many LLMs vote and majority wins" system. A chairman reads a repository snapshot and creates a neutral opening statement; configured expert models answer independently; the chairman then checks the discussion against repository evidence, preserves minority positions, identifies unresolved claims, and proposes the next agenda. A human decides whether to continue, redirect, investigate, or stop.

## Workflow

```text
Repository + docs + decision history
              |
              v
      Chairman reads snapshot
              |
              v
       Neutral opening
              |
    +---------+----------+
    v         v          v
 Expert A  Expert B   Expert N     (parallel, isolated)
    |         |          |
    +---------+----------+
              v
      Chairman synthesis
   consensus / disagreement
    evidence / uncertainty
              |
              v
          HUMAN GATE
    +---------+----------+------------+
    v         v          v            v
  STOP     CONTINUE   REDIRECT    INVESTIGATE
```

## Design principles

- **Independent first responses.** Experts see the chairman's opening statement, not one another's answers.
- **Neutral chairman opening.** The chairman is explicitly instructed not to reveal a preferred solution before experts answer.
- **Evidence over voting.** The synthesis is required to separate repository-grounded facts, assumptions, unverified claims, and minority arguments.
- **Human controls the rounds.** There is no automatic "debate until consensus" loop.
- **Persistent sessions.** Every opening, expert response, synthesis, human action, repository path, and Git commit is stored in SQLite.
- **Provider compatibility layer.** Every model independently configures its endpoint, API key, model name, headers, parameters, and wire protocol.

## Supported model protocols

The backend uses raw HTTP rather than vendor SDKs so custom gateways work naturally.

- `openai_responses`: `POST .../v1/responses`, Bearer auth; uses `instructions` + `input`.
- `anthropic_messages`: `POST .../v1/messages`, `x-api-key` + `anthropic-version`; uses `system` + `messages`.
- `openai_chat_completions`: optional compatibility dialect for vendors/gateways that still expose `POST .../v1/chat/completions`.

Each model may use a distinct `api_url` and a distinct `api_key_env` (or literal `api_key`, although environment variables are strongly recommended).

## Quick start

### 1. Configure models

```bash
cp config.example.yaml config.yaml
export CHAIRMAN_API_KEY=...
export GPT_EXPERT_API_KEY=...
export CLAUDE_EXPERT_API_KEY=...
export THIRD_PARTY_API_KEY=...
```

Edit `config.yaml` to add/remove any number of experts. The `chairman` and `experts` fields reference model IDs from `models`.

### 2. Run backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cd ..
LLM_EXPERT_GROUP_CONFIG=./config.yaml uvicorn backend.app.main:app --reload --port 8000
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

The repository loader prioritizes README, docs, build metadata, then source directories. Binary files, generated directories, very large files, `.git`, `node_modules`, virtualenvs, and build outputs are skipped. The selected snapshot and Git commit are recorded when the session is created.

## Human actions

After each chairman synthesis, the workflow pauses.

- **Continue** — chairman narrows the next agenda to unresolved disagreements.
- **Redirect** — human supplies a new focus; the next chairman opening follows it.
- **Investigate** — evidence-focused round. Experts are asked to distinguish claims verifiable from the repository snapshot from inference. This v0.1 implementation does not grant shell/web tools to experts yet.
- **Stop** — permanently closes the session.

A session never starts another round until one of these actions is explicitly recorded.

## API surface

- `GET /api/models` — redacted model configuration/status.
- `GET /api/sessions` — session history.
- `POST /api/sessions` — capture repository snapshot and create a council.
- `POST /api/sessions/{id}/rounds/run` — run one round.
- `POST /api/sessions/{id}/action` — record `continue`, `redirect`, `investigate`, or `stop`.

## Current boundaries

This first implementation deliberately keeps the orchestration state machine small and explicit instead of introducing LangGraph. The workflow is deterministic and human-gated, so a custom state machine is easier to inspect and persist. LangGraph can be introduced later if tool-using investigators, branch/fork/replay semantics, or long-running resumable subgraphs justify it.

`INVESTIGATE` currently means a repository-evidence review round over the captured snapshot. A future investigator can add controlled shell commands, tests, web research, GitHub retrieval, or MCP tools without changing the core council protocol.

## Security notes

- Keep API keys in environment variables; `config.yaml` is ignored by Git.
- Repository content is sent to the chairman model. Expert models receive the chairman's opening statement, not the raw repository snapshot; the chairman receives the raw snapshot again during synthesis for fact checking.
- Treat repositories as potentially sensitive input and configure providers accordingly.
- For OpenAI Responses, the example config uses `store: false` to avoid application-state retention where supported.

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

1. Streaming round progress with SSE/WebSocket.
2. Tool-using investigator role (shell/tests/web/GitHub/MCP) with an explicit permission boundary.
3. Repository refresh/diff between rounds instead of a fixed creation-time snapshot.
4. Dual-chair validation for high-impact final decisions.
5. Exportable decision report and machine-readable session bundle.
6. Replay/fork from any council round.
