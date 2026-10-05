# Reviewer

Harness: Pinned official isolated event harness + independent black-box assurance
Model: No LLM — deterministic Python verification

## Mission

Attempt to disprove the exact committed candidate independently from the complete supplied requirements.

## Rules

- Bind every verdict to the exact result commit.
- Check inherited behavior, negative paths, boundaries, concurrency, retry behavior, state transitions, migration, and user-visible states where applicable.
- Treat shipped checks as evidence, not the full acceptance authority.
- Never modify production code.
- A rejection must include reproducible evidence.
- An acceptance must preserve residual unknowns.
- Never ask the human for steering during a dark-factory run.
