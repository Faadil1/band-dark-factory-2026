# Pocketful cumulative spec-derived assurance

This assurance is intentionally separate from the product implementation and from the shipped public harness.

It runs against the exact accepted Stage 4 revision `f2744a48d31987732b830c02f77fcf086bae2683` and:

1. re-runs the existing independent Stage 1 black-box assurance against the Stage 4 service to verify inheritance;
2. exercises additional Stage 2–4 requirements derived from the written specs, including holds/capture authority and release, historical effective-vs-recorded-time views, statement snapshot stability, revision privacy, historical overdraft rejection, refunds against available funds, correction/refund immutability, settlement-wide batch corrections, replay/atomicity, concurrent expected revisions, and Stage 3→4 import preservation.

This is additional assurance, not hidden-test evidence and not exhaustive proof of every normative requirement. Product code is not modified by this PR.
