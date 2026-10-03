# BAND Dark Factory — Factory Contract

Status: **PRE-REHEARSAL / NOT SUBMISSION READY**

This repository will contain the factory and the service it produces.

## Current factory shape

Three generic seats are used for the first rehearsal:

1. **Coordinator** — interprets supplied requirements, coordinates handoffs and records blockers.
2. **Implementer** — writes production code from the complete supplied specification and repairs rejected work.
3. **Reviewer** — independently checks the exact committed result against the written specification and rejects or accepts it.

Additional seats are added only if the Toy Factory shows a causal benefit that justifies coordination cost.

## Core invariant

No stage is promoted unless the exact committed candidate is independently checked against:
- the complete applicable written specification;
- inherited requirements;
- stage-boundary constraints;
- clean-runtime requirements;
- required user-facing behavior.

A green public harness is evidence, not acceptance authority.

## Dark-factory rule

For a submitted stage run, the human supplies the stage task once. From dispatch until the Coordinator's terminal report:
- no seat asks the human for clarification, approval or confirmation;
- seats communicate with one another in BAND;
- rejected work returns to the responsible owner;
- repaired work passes through independent review again.

## Mandate boundary

Standing mandate files are generic. They must not contain track-specific:
- endpoint paths;
- field names;
- error codes;
- business-domain rules.

The stage task/spec provides domain content.

## Runtime architecture

- BAND: coordination, room, seat identities, handoffs and room evidence.
- Remote agent runtime: cloud/GitHub-hosted or other non-workstation execution only.
- GitHub: canonical operational repository and commit history.
- GitHub Actions: Docker, Playwright and official harness execution.
- Work computer: BAND/browser control surface only; no broad agent filesystem access.

## Current evidence boundary

Proven:
- remote Ubuntu runner can execute the official isolated harness;
- untouched Toy scaffold reproduces the documented 2/8 baseline.

Not yet proven:
- this repo's Actions workflow;
- remote BAND agent connectivity;
- reciprocal seat messaging;
- autonomous Toy Factory;
- real-track stage conformance;
- hidden tests.

## Cost/time measurement

For every rehearsal and real stage run capture:
- wall-clock elapsed time;
- model/harness used by each seat;
- available provider spend/usage basis;
- rejection/repair count;
- highest accepted contiguous stage.

## Promotion

Current promotion target: **TECHNICAL_REALITY_CHECK → TOY_FACTORY_REHEARSAL**.

No real Pocketful run may begin before Track Lock.
