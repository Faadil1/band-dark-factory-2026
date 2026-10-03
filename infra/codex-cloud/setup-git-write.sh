#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="Faadil1/band-dark-factory-2026"
REMOTE_URL="https://github.com/${REPO_SLUG}.git"

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "GH_TOKEN is required as a Codex Cloud environment secret." >&2
  exit 1
fi

# Fine-grained PATs are intended for narrowly scoped automation. Validate the
# token against this repository without printing it.
HTTP_CODE="$(curl --silent --show-error --output /tmp/band-codex-repo.json --write-out "%{http_code}"   -H "Authorization: Bearer ${GH_TOKEN}"   -H "Accept: application/vnd.github+json"   -H "X-GitHub-Api-Version: 2022-11-28"   "https://api.github.com/repos/${REPO_SLUG}")"

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "GH_TOKEN cannot read the configured repository (HTTP $HTTP_CODE)." >&2
  exit 1
fi
rm -f /tmp/band-codex-repo.json

# Keep the credential in Git's in-memory credential-cache daemon rather than
# embedding it in source, the remote URL, or a plaintext credential file.
# Container caching must remain OFF so this setup is executed for every task.
git config --global credential.helper "cache --timeout=7200"

printf 'protocol=https\nhost=github.com\nusername=x-access-token\npassword=%s\n\n' "$GH_TOKEN"   | git credential approve

unset GH_TOKEN

# Codex Cloud task checkouts may arrive without an origin remote.
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

git config user.name "BAND Codex Cloud"
git config user.email "band-codex-cloud@users.noreply.github.com"

# Fail closed unless the credential cache can authenticate Git itself.
git ls-remote origin HEAD >/dev/null

echo "Codex Cloud GitHub write bootstrap configured."
echo "origin=$(git remote get-url origin)"
echo "credential_backend=git-credential-cache"
