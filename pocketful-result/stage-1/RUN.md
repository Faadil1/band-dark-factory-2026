# Pocketful Stage 1 — run

Zero-dependency Node.js service (built-in `http` and `crypto` only); no outbound network is needed at runtime.

Build and start (from this directory):

```sh
docker build -t pocketful-stage-1 . && docker run --rm -e PORT=8080 -p 8080:8080 pocketful-stage-1
```

Check: `curl http://localhost:8080/health` → `{"status":"ok"}`

State is held in memory (single-threaded, so every operation is atomic) and is replaced by
`POST /_test/reset` or `POST /_test/import`.
