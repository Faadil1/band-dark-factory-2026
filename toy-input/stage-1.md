# `toy` — stage 1: a shared counter

Build a tiny HTTP service that stores one number. This practice exercise is unscored; it
exists to run the whole build-and-deliver loop once on something small.

## Deliverable

Create the service source, a `Dockerfile`, and a short `RUN.md` in one directory.
The command in `RUN.md` must build and start the service with no manual steps.
Stage 1 needs only an API. Any language or framework is fine; memory-only storage is
fine. The counter starts at **0** when the service starts.

Bind `0.0.0.0` and read the listening port from `PORT`, defaulting to `8080`.
Your `Dockerfile` is built and the container started, with up to 60 seconds to become
healthy. Limits: 2 CPUs, 2 GiB memory, 5 seconds per request (10 for reset).
Install dependencies during the Docker build; no internet is available at run time.

## Four endpoints

All endpoints are public. JSON responses use `Content-Type: application/json`;
adding `charset=utf-8` is fine.

| Request | Response | Effect |
|---|---|---|
| `GET /health` | `200 {"status":"ok"}` | None |
| `GET /counter` | `200 {"value":0}` | Returns the current value; does not change it |
| `POST /counter/increment` | `200 {"value":1}` | Adds exactly 1 and returns the new value |
| `POST /_test/reset` with `{"value":7}` | `204`, empty body | Replaces the value with 7 |

The numbers above are examples. All clients share the same counter. Two successive
increments from 7 return 8, then 9; the next read returns 9.

Increment accepts an empty request body or `{}`. Every request is a new increment.
Reset is synchronous: once it returns, the next read must see the seeded value.
Reset fixtures are always valid: an object with an integer `value` between 0 and
1,000,000. Reset is called repeatedly, and no earlier state may remain.

There are no accounts, passwords, tokens, idempotency keys, or database requirements.
