# Pocketful Stage 4 — run

Zero-dependency Node.js service (built-in `http`, `crypto`, `fs` only). The browser UI (HTML, CSS, JS,
icon) is served from the same container using system fonts, so no outbound network is needed at runtime.

Build and start (from this directory):

```sh
docker build -t pocketful-stage-4 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-4
```

Check: `curl http://localhost:8080/health` → `{"status":"ok"}`; open `http://localhost:8080/login` in a browser.

- Screens: `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`, `/statement`. `/requests`,
  `/authorizations` and `/statement` return the UI for `Accept: text/html` and JSON otherwise.
- Stage 3 temporal ledger is unchanged: payment `created_at`, `GET /me?as_of=&known_at=`, `GET /statement`
  (with `snapshot` pagination), `POST /payments/{id}/corrections`, `GET /payments/{id}/revisions`.
- Stage 4 adds `POST /payments/{id}/refunds` (receiver only, from available funds, capped by the payment's
  current corrected amount; payments expose `refund_of`) and `POST /correction-batches` (settlement
  operators; 1..32 distinct payments applied atomically with one shared `recorded_at`).
- Batch error precedence: item errors in input order, settlement completeness (`incomplete_settlement`) and
  shared effective instants, combined current affordability (`insufficient_funds`), then historical total and
  available funds at every effective/event boundary (`historical_overdraft`).
- Captures and refunds are immutable; settlement members can only be corrected through a batch that includes
  every member. Earlier receipts, revision history and statement snapshots are never rewritten.
- Instants are emitted in UTC with millisecond precision (the fraction is omitted for whole seconds).
- State is held in memory (single-threaded, so every operation is atomic) and is replaced by
  `POST /_test/reset` or `POST /_test/import`. Imports accept stage-1, stage-2 and stage-3 exports;
  opening balances are reconstructed when absent.
- Authorization expiry is evaluated against the clock on every request; no timers are needed.
