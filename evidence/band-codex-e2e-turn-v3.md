# BAND to Codex end-to-end Technical Reality probe v3

Status: awaiting autonomous round trip.

Expected result:
- Coordinator dispatches the bounded task in BAND.
- Implementer observes the task from BAND.
- Implementer causes a Codex Cloud task through the GitHub bridge.
- Codex returns a bounded machine-readable patch.
- GitHub Actions validates, commits, and pushes the exact candidate.
- Implementer records the resulting receipt back in BAND from the same relay workflow.
- Coordinator observes both the task and receipt in the shared BAND room.

This probe does not start the Toy Factory or Pocketful build.
