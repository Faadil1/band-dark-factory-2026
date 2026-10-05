# BAND Dark Factory — Toy Rehearsal 8 Trigger

Opening this pull request is the single initial human dispatch for fresh Toy Factory Rehearsal #7 using Claude Code OAuth as the Implementer runtime.

No Toy stage implementation is pre-seeded. From PR open onward, Coordinator → Implementer/Claude Code → Reviewer must proceed without human steering. The run must end in ACCEPT, REJECT, or an explicit fail-closed BLOCKED terminal marker.

Claude may use up to 40 turns on the initial implementation. If the first independent Reviewer pass returns REJECT, the Coordinator must route the rejection back to the Implementer automatically; Claude Code may repair once with up to 32 turns, after which the exact repaired revision must be independently reviewed again.
