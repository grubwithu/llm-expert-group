# Architecture

## Why no agent framework in v0.1

The control flow is deliberately small:

`READY -> RUNNING -> AWAITING_HUMAN -> READY | STOPPED`

A framework such as LangGraph would be useful once the council contains nested tool-using investigators, asynchronous jobs, replay/fork semantics, or complex checkpoint recovery. For the current human-gated protocol, a small explicit state machine has fewer hidden semantics and makes persistence easier to audit.

## Components

### Repository snapshotter

Reads a bounded, prioritized text snapshot of a local repository and records the current Git commit when available. The snapshot is frozen for the session so later model disagreement is not confused with changing source context.

### Chairman

The chairman has two calls per round:

1. **Opening**: sees the repository snapshot and prepares a neutral agenda.
2. **Synthesis**: sees repository snapshot + expert responses and evaluates claims against evidence.

The chairman must preserve minority positions and uncertainty. It may recommend a direction but cannot silently convert an unverified claim into a repository fact.

### Experts

Experts run in parallel and are isolated from each other. They receive only the chairman opening, so the first-order diversity is not contaminated by other models' prose.

### Human gate

The workflow cannot advance automatically after synthesis. A human records exactly one action:

- `continue`
- `redirect` (requires a note)
- `investigate` (requires a note)
- `stop`

### Provider adapter layer

`ModelAdapter.generate(system, prompt) -> text` is the only interface used by the council.

Adapters own wire-format differences:

- authentication headers;
- endpoint normalization;
- request JSON;
- response text extraction.

The rest of the system has no OpenAI/Anthropic-specific branches.

## Persistence model

`CouncilSession`

- repository path
- repository commit
- frozen repository context
- status
- current round

`CouncilRound`

- opening statement
- all expert results (including provider failures)
- chairman synthesis
- human action and note
- round kind (`discussion` or `investigation`)

## Failure behavior

A single expert provider failure is recorded and does not abort the round. If every expert fails, the round fails. Chairman failure aborts the round because there is no valid opening/synthesis boundary.

## Future tool boundary

A future investigator should not inherit unrestricted shell access implicitly. Tool permissions should be configured per investigator/session, with command/evidence logs persisted separately from natural-language claims.
