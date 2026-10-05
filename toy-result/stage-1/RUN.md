# Run

```
docker build -t toy . && docker run --rm -p 8080:8080 toy
```

Listens on `0.0.0.0:$PORT` (default 8080). No dependencies; state is in memory.
