# Pocketful Stage 2 — run

Zero-dependency Node.js service (built-in `http`, `crypto`, `fs` only). The browser UI (HTML, CSS, JS,
icon) is served from the same container using system fonts, so no outbound network is needed at runtime.

Build and start (from this directory):

```sh
docker build -t pocketful-stage-2 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-2
```

Check: `curl http://localhost:8080/health` → `{"status":"ok"}`; open `http://localhost:8080/login` in a browser.

- Screens: `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`. `/requests` and
  `/authorizations` return the UI for `Accept: text/html` and JSON otherwise.
- State is held in memory (single-threaded, so every operation is atomic) and is replaced by
  `POST /_test/reset` or `POST /_test/import`. Imports accept stage-1 exports.
- Authorization expiry is evaluated against the clock on every request; no timers are needed.
