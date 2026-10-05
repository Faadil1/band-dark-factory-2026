# `toy` — stage 2: one page, one button

Keep the stage 1 API working. The deliverable is unchanged: the service source, a
`Dockerfile`, and a short `RUN.md` in one directory, and the command in `RUN.md`
builds and starts the service with no manual steps.

Add a page at `/` with these two elements:

| `data-testid` | Element |
|---|---|
| `counter-value` | Visible text containing only the current integer, e.g. `7` |
| `increment-button` | A button that adds 1 |

On page load, read the value from `GET /counter`. Clicking the button calls
`POST /counter/increment` once and displays the returned value. Reloading the page
shows the server's current value, including increments made by another client.

Any layout is fine. Serve all assets from the container; no CDN is available at run
time. Elements are located by the exact `data-testid` values above and by nothing else.

Stage 1 must still pass.
