# Pocketful — BAND Dark Factory final result

This repository is the result of the final fresh dark-factory run.

It contains four complete, independently reviewed stages:

- `stage-1/`
- `stage-2/`
- `stage-3/`
- `stage-4/`

Each later stage extends the accepted prior stage. Each stage is independently buildable from its own `Dockerfile` and documented in its own `RUN.md`.

The factory uses three distinct BAND seats: Coordinator, Implementer, and Reviewer. Their reusable standing instructions are in `mandates/`. The product-specific requirements are supplied only in the BAND room, not embedded in those mandates.

## Evidence boundary

The final run is designed to use one fresh BAND room and this fresh git repository from Stage 1 through Stage 4, with no human steering between stage dispatches. The full BAND session must be downloaded from the BAND console after the run and committed unchanged as `room.json` before submission.

A public harness pass is evidence, not a claim that hidden tests or every normative requirement are proven. Independent spec-derived black-box checks are also run, but hidden-test success and exhaustive conformance remain explicitly unknown.

## Run

Follow each stage's `RUN.md`. The official event harness builds the service from the selected stage folder and communicates with it over HTTP.
