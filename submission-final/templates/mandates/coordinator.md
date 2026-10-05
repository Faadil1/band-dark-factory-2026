# Coordinator

Harness: BAND Agent API + GitHub Actions deterministic orchestration
Model: No LLM — deterministic Python orchestration

## Mission

Own stage sequencing, complete handoffs, exact revision binding, and fail-closed progress.

## Rules

- Supply the complete applicable written requirements in every delegated handoff.
- Keep all stage decisions inside the shared BAND room.
- Start the next stage only after independent acceptance of the current exact commit.
- Route a rejection back to the Implementer, then require independent re-review.
- Record concrete blockers instead of inventing requirements.
- Never write product implementation.
- Never ask the human for clarification, approval, confirmation, or debugging help during a dark-factory run.
