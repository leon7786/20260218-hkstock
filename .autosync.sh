#!/usr/bin/env bash
set -euo pipefail
cd /root/.openclaw/workspace/20260218-hkstock

# 避免并发
LOCKFILE=/tmp/hkstock-autosync.lock
exec 9>"$LOCKFILE"
flock -n 9 || exit 0

# 基本前置检查：必须在 git repo
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: not a git repo" >&2
  exit 2
fi

# 如果处于 rebase/merge 中，直接退出（避免把半成品推上去）
if [[ -d .git/rebase-merge || -d .git/rebase-apply || -f .git/MERGE_HEAD ]]; then
  echo "WARN: git operation in progress (rebase/merge). Skip autosync." >&2
  exit 0
fi

# 仅在有变更时提交并推送
if git diff --quiet && git diff --cached --quiet; then
  exit 0
fi

git add -A
if git diff --cached --quiet; then
  exit 0
fi

# 简单校验 index.html（避免推送损坏 HTML）
python3 - <<'PY'
import re, sys
p='docs/index.html'
try:
  t=open(p,encoding='utf-8').read()
except FileNotFoundError:
  sys.exit(0)
rows=re.findall(r'<tr>.*?</tr>', t, re.S)
# 第一行是表头 <tr><th...> 不算数据行
bad=[]
for r in rows[1:]:
  td=len(re.findall(r'<td\b', r))
  if td and td < 10:
    bad.append(td)
if bad:
  print('ERROR: malformed rows (td too few):', bad[:10], file=sys.stderr)
  sys.exit(1)
PY

git commit -m "auto-sync: $(date '+%F %T %z')" || exit 0

# pull/rebase 失败就 abort 并退出，避免错误历史 push
if ! git pull --rebase --autostash origin master; then
  git rebase --abort >/dev/null 2>&1 || true
  echo "ERROR: rebase failed. Skip push." >&2
  exit 1
fi

git push origin master
