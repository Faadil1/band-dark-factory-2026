# Pocketful Stage 1 — independent spec-derived assurance

Target revision: `b27a7dcc627637be4cad037cb59c369c36181b63`.

This suite is derived from the normative Stage 1 specification, not from the implementation.
It runs black-box against the exact accepted container and supplements—rather than replaces—the
official shipped harness.

Covered adversarial families:
- conservation and nonnegative balances;
- success/failure/retry idempotency semantics;
- request authority and later-pay recovery;
- split rounding including zero shares;
- export/import replacement with token and idempotency preservation;
- settlement authority, atomic failure and replay;
- concurrent unique payments and identical idempotent payments;
- derived-handle collision behavior.

Passing this suite does not prove hidden-test success.
