# Codex Cloud GitHub write bootstrap

Purpose: give the Codex Cloud runtime narrowly scoped GitHub write access without an OpenAI API key and without embedding a token in source control or a Git remote URL.

## Required secret

Save the short-lived GitHub fine-grained personal access token in the Codex Cloud environment as:

`GH_TOKEN`

Recommended scope:
- Resource owner: `Faadil1`
- Repository access: only `band-dark-factory-2026`
- Contents: Read and write
- Metadata: Read
- Pull requests: only if a later workflow truly needs it
- Expiration: immediately after the hackathon

Do not grant Actions, Administration, Secrets, or account-wide repository access.

## Codex Cloud environment

Use:

```bash
bash infra/codex-cloud/setup-git-write.sh
```

Required environment settings:
- Container caching: **Off** — the secret is setup-only, so the credential cache must be seeded for every task.
- Agent internet access: **On**
- Additional allowed domains: `github.com, api.github.com`
- HTTP methods: allow the methods required for Git HTTPS push during this bounded test.

The script:
- validates the fine-grained token against this repository using the GitHub API;
- seeds Git's in-memory `credential-cache`;
- removes `GH_TOKEN` from the setup shell;
- configures an HTTPS `origin` without credentials in its URL;
- verifies authenticated Git access with `git ls-remote`.

The token is not written into the repository, a Git remote URL, or a plaintext credential file.

## Security boundary

The task's Git process can use the cached credential for the duration of the container. Keep the token:
- repository-scoped;
- short-lived;
- minimally permissioned;
- revoked immediately after the hackathon.

Internet access should remain limited to the GitHub domains needed for this workflow.

## Truth boundary

The bootstrap is not itself proof of autonomous publication. The gate closes only when a new Codex Cloud task creates a bounded commit and the intended GitHub branch head changes without human publication.
