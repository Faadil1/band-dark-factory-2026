# BAND Dark Factory — Submission Factory

## Factory shape

The factory uses three stable, generic seats.

1. **Coordinator** — deterministic orchestration over the BAND Agent API and GitHub Actions. It creates one room, supplies the complete cumulative requirements in every delegated handoff, advances stages only after independent acceptance, records blockers, and never writes product code.
2. **Implementer** — Claude Code running through OAuth in GitHub Actions. It writes only the current stage inside a fresh result repository, preserving inherited behavior and repairing a rejected revision when necessary.
3. **Reviewer** — deterministic independent verification. It receives the complete cumulative requirements and exact committed revision, runs the pinned official isolated harness, rejects observable counterexamples, and never repairs product code.

The factory deliberately keeps standing mandates domain-generic. Product vocabulary and requirements enter only through the stage task sent in the BAND room.

## Dark-factory invariant

The opening trigger is the only human input during the run. From creation of the fresh room until the Coordinator's terminal report:

- no seat asks the human for clarification, approval, debugging help, or confirmation;
- Stage N+1 cannot begin before Stage N is independently accepted;
- every implementation handoff names the exact fresh-result commit;
- a rejection returns to the Implementer and must be independently re-reviewed;
- failure to reach an accepted state blocks the chain rather than being presented as success.

## Fresh-result construction

The run initializes a new git repository containing only this factory description and the three mandates. Stage 1 is built from the written requirements. After acceptance, the Coordinator copies the accepted folder forward and commits that inheritance before the Implementer extends it for the next stage. The same room and result repository continue through all four stages.

Earlier product implementations are removed from the execution workspace before the Implementer runs, so the final result is not copied from a prior solution.

## Independent verification

The Reviewer runs the official event harness in isolated mode on each exact stage commit. After Stage 4 acceptance, the factory also runs independent black-box suites derived from requirements that the shipped public checks may not cover.

During factory development, that extra assurance found a real compatibility defect after an otherwise green public Stage 4 run: an earlier saved view changed serialized shape after import into the next stage. The public harness had not exposed it. The defect was preserved as negative-event evidence, repaired, and reverified. That incident is why independent assurance remains load-bearing rather than decorative.

## Reproducibility and result evidence

Every stage contains source, `Dockerfile`, and `RUN.md`. The final workflow records wall-clock duration, accepted attempt per stage, exact result commits, public-harness reports, and additional assurance reports. Provider monetary spend is not exposed by the subscription runtime; that absence is recorded instead of estimated.

The full BAND session is not fabricated or fetched by the harness. After the terminal room message, the human must use BAND's **Download full session** action and save the download unchanged as `room.json` at repository root. Only after that binding can the offline submission check and final canonical assurance complete.

## Truth boundary

A green public harness plus additional independent tests materially strengthens confidence. It does not prove hidden-test success, exhaustive normative conformance, or production financial-system readiness. Those boundaries remain explicit.
