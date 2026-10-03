# Codex Cloud GitHub write bootstrap

Purpose: give the Codex Cloud runtime repository-scoped GitHub write access without using an OpenAI API key and without placing a token in source control or a Git remote URL.

## Required secret

Create a short-lived GitHub fine-grained personal access token and save it in the Codex Cloud environment as:

`GH_TOKEN`

Recommended scope:
- Resource owner: `Faadil1`
- Repository access: only `band-dark-factory-2026`
- Repository permissions:
  - Contents: Read and write
  - Pull requests: Read and write
  - Metadata: Read
- Expiration: immediately after the hackathon (for example 2026-10-07)

Do not grant Actions, Administration, Secrets, or organization-wide permissions.

## Codex Cloud environment

Set the environment setup script to:

```bash
bash infra/codex-cloud/setup-git-write.sh
```

The script:
- authenticates GitHub CLI using the environment secret;
- removes `GH_TOKEN` from the current shell after authentication;
- configures the GitHub CLI credential helper;
- adds `origin=https://github.com/Faadil1/band-dark-factory-2026.git`;
- verifies authenticated repository access;
- never embeds the token in the remote URL.

Runtime network access to GitHub must be allowed for the task that pushes.

## Truth boundary

This bootstrap does not itself prove autonomous push. After configuration, run the bounded Codex Cloud probe again and require an exact commit to appear on the intended GitHub branch without human publication.
