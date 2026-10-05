# `toy` — stage 4: increment by a chosen amount

Stages 1, 2 and 3 must still pass, and that is most of the work.

`POST /counter/increment` accepts an optional `by` in its request body:

| Request body | Response | Effect |
|---|---|---|
| `{"by": 5}` from 7 | `200 {"value":12}` | Adds 5 |
| absent, `{}`, or `{"by": 1}` | `200 {"value":8}` | Adds 1, exactly as before |
| `{"by": 0}`, `{"by": -1}`, `{"by": "5"}` | `400`, any body | None — the value does not move |

`by` is an integer of 1 or more. Zero, a negative number, a string and a fraction are
all rejected with `400` and change nothing; the next request works normally. A request
with no body, or with `{}`, still means 1, which is why stages 1 to 3 keep behaving
identically.

The page from stage 2 is unchanged: its button still adds 1.

> **The stage-3 rule is the same in words and wider in effect:** nothing may be lost
> when 20 clients increment together. It now covers amounts, not just counts. Twenty
> clients sending `by` of 1 through 20 move the counter by exactly 210, and no two of
> them may be told the same value.

If the amount is added outside the lock, or read before the lock and written after it,
this is where it shows.
