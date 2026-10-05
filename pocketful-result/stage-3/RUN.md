# Pocketful Stage 3 — run

Zero-dependency Node.js service (built-in `http`, `crypto`, `fs` only). The browser UI (HTML, CSS, JS,
icon) is served from the same container using system fonts, so no outbound network is needed at runtime.

Build and start (from this directory):

```sh
docker build -t pocketful-stage-3 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-3
```

Check: `curl http://localhost:8080/health` → `{"status":"ok"}`; open `http://localhost:8080/login` in a browser.

- Screens: `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`, `/statement`. `/requests`,
  `/authorizations` and `/statement` return the UI for `Accept: text/html` and JSON otherwise.
- Stage 3 adds the temporal ledger: payment `created_at`, `GET /me?as_of=&known_at=`, `GET /statement`
  (with `snapshot` pagination), `POST /payments/{id}/corrections` and `GET /payments/{id}/revisions`.
- Every payment carries an append-only revision history (`effective_at` = when money took effect,
  `recorded_at` = when the service learned it). Balances, holds and statements are derived from the
  latest revisions known at `known_at`, applied at their effective times.
- Instants are emitted in UTC with millisecond precision (the fraction is omitted for whole seconds).
- State is held in memory (single-threaded, so every operation is atomic) and is replaced by
  `POST /_test/reset` or `POST /_test/import`. Imports accept stage-1 and stage-2 exports; opening
  balances are reconstructed from them.
- Authorization expiry is evaluated against the clock on every request; no timers are needed.
