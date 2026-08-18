CHAIRMAN_SYSTEM = """You are the chairman of a technical expert council.
Your job is to curate context, moderate neutrally, identify real disagreements, distinguish evidence from assumptions, and keep a precise record.
You may evaluate proposals, but you are not a technical dictator and you must preserve minority positions and unresolved uncertainty.
When referencing repository facts, cite the file path and relevant symbol/section when possible.
Never invent repository facts that are not in the supplied snapshot.
"""

EXPERT_SYSTEM = """You are an independent technical expert in a multi-model council.
Form your own view from the chairman's opening statement. Do not assume a majority is correct.
Be explicit about assumptions, failure modes, falsification conditions, and evidence needed.
Prefer reversible, testable decisions over confident speculation.
"""


def first_opening_prompt(topic: str, repo_context: str, commit: str | None, truncated: bool) -> str:
    return f"""Prepare the neutral opening statement for round 1.

TOPIC FROM HUMAN:
{topic}

REPOSITORY COMMIT:
{commit or 'not available'}

REPOSITORY SNAPSHOT TRUNCATED:
{truncated}

REPOSITORY SNAPSHOT:
{repo_context}

The opening statement must contain these sections:
1. Topic / decision question
2. Current repository state relevant to the topic
3. Known constraints and already-frozen decisions (only if evidenced)
4. Known uncertainties
5. Candidate directions already visible in the repository or implied by the topic, without endorsing one
6. Exact questions the experts should answer
7. Required response format: Recommendation, Reasoning, Assumptions, Risks, Evidence Needed, Falsification Condition, Cheapest Discriminating Experiment, Confidence (0-100)

Do NOT announce your preferred solution. Avoid anchoring the experts.
"""


def next_opening_prompt(*, topic: str, repo_context: str, previous_summary: str, action: str, note: str | None, round_number: int) -> str:
    mode = {
        "continue": "Narrow the agenda to unresolved disagreements from the previous round.",
        "redirect": "Follow the human redirect as the primary agenda while preserving relevant prior context.",
        "investigate": "Treat this as an evidence-focused investigation round. Ask experts to verify the named uncertainty against repository evidence and clearly separate observed facts from inference.",
    }[action]
    return f"""Prepare the neutral opening statement for round {round_number}.

ORIGINAL TOPIC:
{topic}

PREVIOUS CHAIRMAN SYNTHESIS:
{previous_summary}

HUMAN ACTION: {action}
HUMAN NOTE:
{note or '(none)'}

INSTRUCTION FOR THIS ROUND:
{mode}

REPOSITORY SNAPSHOT (for fact checking by the chairman):
{repo_context}

Do not repeat settled material unless needed. Convert vague disagreement into precise questions.
Do not reveal a preferred answer. For an investigation round, identify concrete claims that can be confirmed or falsified from the repository snapshot.
"""


def expert_prompt(opening_statement: str, round_number: int, kind: str) -> str:
    return f"""Council round {round_number} ({kind}).

CHAIRMAN OPENING STATEMENT:
{opening_statement}

Respond independently in Markdown using exactly these headings:
## Recommendation
## Reasoning
## Assumptions
## Risks / Failure Modes
## Evidence Needed
## Falsification Condition
## Cheapest Discriminating Experiment
## Confidence

If the available information is insufficient, say so explicitly rather than forcing a recommendation.
"""


def synthesis_prompt(*, topic: str, repo_context: str, opening: str, responses: list[tuple[str, str]], round_number: int) -> str:
    rendered = "\n\n".join(f"===== EXPERT {name} =====\n{text}" for name, text in responses)
    return f"""Synthesize council round {round_number}.

ORIGINAL TOPIC:
{topic}

OPENING STATEMENT:
{opening}

EXPERT RESPONSES:
{rendered}

REPOSITORY SNAPSHOT FOR EVIDENCE CHECKING:
{repo_context}

Produce Markdown with these sections:
## Executive Evaluation
## Consensus
## Majority / Leading Positions
## Minority Positions
## Core Disagreements
## Repository-Grounded Evidence Check
## Unverified Claims
## Experiments That Would Resolve the Disagreement
## Chairman Recommendation
## Uncertainty / Why This Recommendation Could Be Wrong
## Proposed Next-Round Agenda

Do not reduce the discussion to vote counts. A minority argument can dominate if it is better supported.
Explicitly call out expert claims that conflict with repository evidence or cannot be verified from the snapshot.
"""
