# Pocketful cumulative spec-derived assurance

This assurance is intentionally separate from the shipped public harness and is used as a fail-closed product-assurance layer.

The first run against accepted revision `f2744a48d31987732b830c02f77fcf086bae2683` found a real Stage 3→4 compatibility defect: imported Stage 3 statement snapshots were re-rendered with the Stage 4-only `refund_of: null` field instead of remaining in their original form. PR #98 is retained closed/unmerged as negative-event evidence.

The repair candidate is verified in three layers:

1. the pinned official Pocketful harness runs with `--stage 4 --mode isolated` against the exact PR candidate;
2. the existing independent Stage 1 black-box assurance is rerun against the Stage 4 service to verify inherited behavior;
3. the Stage 2–4 cumulative suite exercises holds/capture authority and release, historical effective-vs-recorded-time views, statement snapshot stability, revision privacy, historical overdraft rejection, refunds against available funds, correction/refund immutability, settlement-wide batch corrections, replay/atomicity, concurrent expected revisions, and Stage 3→4 import preservation.

Passing these checks materially strengthens assurance but still does **not** prove hidden-test success or exhaustive conformance to every normative requirement.
