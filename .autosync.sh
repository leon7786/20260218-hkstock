#!/usr/bin/env bash
set -e
cd /root/.openclaw/workspace/20260218-hkstock

# 避免并发
LOCKFILE=/tmp/hkstock-autosync.lock
exec 9>"$LOCKFILE"
flock -n 9 || exit 0

# 仅在有变更时提交并推送
if ! git diff --quiet || ! git diff --cached --quiet; then
  git add -A
  if ! git diff --cached --quiet; then
    git commit -m "auto-sync: $(date '+%F %T %z')" || exit 0
    git pull --rebase --autostash origin master || true
    git push origin master
  fi
fi
