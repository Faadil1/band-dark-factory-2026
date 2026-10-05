# BAND Dark Factory — Toy Rehearsal 6

Fresh unscored rehearsal of the official four-stage `toy` track using Claude Code OAuth as the Implementer runtime.

Purpose:
- prove Coordinator → Implementer → Reviewer handoffs in a fresh BAND room;
- prove Claude Code builds all four Toy stages autonomously from the written specs;
- prove bounded validation plus GitHub Actions commit/push of the exact candidate;
- run the official isolated Toy harness independently;
- if attempt 1 is rejected, automatically route the rejection back to Claude for one repair and independent re-review;
- record a terminal ACCEPT, REJECT, or BLOCKED marker bound to the exact reviewed revision.

No `stage-1/` through `stage-4/` implementation is pre-seeded in this branch.
Opening the PR is the single initial human dispatch; no human steering is permitted after PR open.
