# `toy` — stage 3: no lost increments

No new endpoints and no new page elements. Stages 1 and 2 must still pass, unchanged.
What changes is the load: the same API is now called by many clients at the same
moment, and every call has to count.

## Concurrent increments

When 20 clients increment together, all 20 requests must return 200 and the counter
must increase by exactly 20. Each response returns the value immediately after its
own increment: starting at 7, the responses contain each integer from 8 through 27
exactly once, in any arrival order. No transport errors or 5xx responses are allowed.

The burst is repeated three times, from both zero and a nonzero seed.

Reading the value, adding one, and storing it is one operation, not three. Protect it
with a lock or use an atomic database update. Two requests that read the same number
and write the same number have lost an increment, and the final read will show it.
