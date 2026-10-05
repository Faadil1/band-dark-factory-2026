# Run

```
docker build -t toy . && docker run --rm -p 8080:8080 toy
```

Listens on `0.0.0.0:$PORT` (default 8080). No dependencies; state is in memory.
The page is served at `/`. Increments are atomic (single synchronous read-modify-write);
`POST /counter/increment` accepts an optional integer `by` >= 1.
