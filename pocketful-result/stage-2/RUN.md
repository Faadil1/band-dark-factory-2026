# Pocketful Stage 2 — run

Zero-dependency Node.js service (built-in `http` and `crypto` only). The browser UI is a
dependency-free single-page app served from `public/` (HTML, CSS, JS, favicon, system font
stack) — nothing is fetched from outside the container at runtime.

Build and start (from this directory):

```sh
docker build -t pocketful-stage-2 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-2
```

Check: `curl http://localhost:8080/health` → `{"status":"ok"}`; open `http://localhost:8080/` in a browser.

Routes: `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`. `/requests` and
`/authorizations` also are JSON API endpoints: they return the UI only for `Accept: text/html`.

State is held in memory (single-threaded, so every operation is atomic) and is replaced by
`POST /_test/reset` or `POST /_test/import`. Authorization expiry is evaluated against the clock at
the start of every operation. Exports from the stage-1 service import unchanged.
