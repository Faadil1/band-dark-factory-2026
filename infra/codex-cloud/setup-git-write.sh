#!/usr/bin/env bash
set -euo pipefail

REPO_SLUG="Faadil1/band-dark-factory-2026"
REMOTE_URL="https://github.com/${REPO_SLUG}.git"

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "GH_TOKEN is required as a Codex Cloud environment secret." >&2
  exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI (gh) is required in the Codex Cloud image." >&2
  exit 1
fi

# Authenticate gh using the repo-scoped short-lived token, then remove the
# environment variable so subsequent shell output cannot accidentally expose it.
printf '%s' "$GH_TOKEN" | gh auth login --hostname github.com --with-token >/dev/null
unset GH_TOKEN

# Configure Git to use gh's secure credential helper. The token value is not
# written into the repository remote URL.
gh auth setup-git --hostname github.com >/dev/null

# Codex Cloud task checkouts currently arrive without an origin remote.
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

# Use a neutral non-personal identity for autonomous commits.
git config user.name "BAND Codex Cloud"
git config user.email "band-codex-cloud@users.noreply.github.com"

# Fail closed if authenticated read access does not work.
git ls-remote origin HEAD >/dev/null

echo "Codex Cloud GitHub write bootstrap configured."
echo "origin=$(git remote get-url origin)"
gh auth status --hostname github.com
