# Codex GitHub user-authored dispatch credential

## Why this exists

Toy Factory Rehearsals 1–3 showed that `@codex` comments authored by `github-actions[bot]` did not receive a Codex reaction or reply. Diagnostic PR #39 proved that a comment authored by `Faadil1` is accepted by the Codex connector and completes a bounded task.

The factory therefore uses a dedicated user-scoped token only for posting the `@codex` task comments. All other repository writes continue to use the built-in `GITHUB_TOKEN`.

## Required secret

Repository Actions secret:

`CODEX_GITHUB_USER_TOKEN`

## Minimum credential shape

Create a **fine-grained personal access token** owned by `Faadil1` with:

- Repository access: **Only select repositories**
- Repository: **Faadil1/band-dark-factory-2026**
- Repository permission: **Issues — Read and write**
- Shortest practical expiration

Do not grant Contents write, Administration, Actions write, organization-wide access, or access to unrelated repositories.

## Runtime guard

Before creating a BAND room, the dispatch script calls GitHub `/user` with the secret and refuses to proceed unless the authenticated login is exactly `Faadil1`.

The credential is used only for the initial and single retry `@codex` PR-conversation comments. It is never passed to Codex and is never used to push implementation code.

## Failure behavior

If the secret is missing, expired, incorrectly scoped, or authenticates as another user, the rehearsal fails before a fresh BAND room is created. Track Lock remains blocked.
