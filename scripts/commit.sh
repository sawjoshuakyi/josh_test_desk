#!/usr/bin/env bash
# Commit the given paths (if changed) and push, retrying on concurrent pushes from other workflows.
set -euo pipefail
msg="$1"; shift
git config user.name "desk-bot"
git config user.email "desk-bot@users.noreply.github.com"
git add -A "$@" 2>/dev/null || true
if git diff --cached --quiet; then echo "nothing to commit"; exit 0; fi
git commit -q -m "$msg"
for i in 1 2 3 4 5; do
  if git pull --rebase -q origin main && git push -q origin HEAD:main; then echo "pushed"; exit 0; fi
  sleep $((i * 5))
done
echo "push failed"; exit 1
