#!/usr/bin/env bash
# Daily HK stock sync pipeline
# Runs locally at 7:00 BJT, pushes to leon7786/20260218-hkstock
set -euo pipefail

cd /root/Projects/20260531-futu-sync || exit 1

export GIT_SSL_NO_VERIFY=1
# Port 2002 proxy no longer available; transparent proxy handles all traffic
# export PLAYWRIGHT_PROXY="http://127.0.0.1:2002|admin12|Dd;'2131801a"

printf '\n=== [HKStock Daily Sync] Starting at %s ===\n' "$(TZ=Asia/Hong_Kong date '+%F %T %Z')"

# Step: pull latest from remote (avoid conflicts)
git pull origin master 2>&1 || true

# Step: run Futunn-only sync pipeline
python3 scripts/sync_futunn_to_pages.py

# Step: merge extra IPO data (绿鞋/公开发售/基石投资者) after refresh
python3 scripts/merge_pending_ipo_extra.py

# Step: commit & push if changed
git add docs/ scripts/ .github/workflows/ package.json package-lock.json requirements-sync.txt
if git diff --cached --quiet; then
    echo "No changes to commit"
else
    git commit -m "chore(sync): daily futunn update $(TZ=Asia/Hong_Kong date +%Y-%m-%d)"
    git push origin master 2>&1
    echo "Push OK"
fi

printf '\n=== [HKStock Daily Sync] Finished at %s ===\n' "$(TZ=Asia/Hong_Kong date '+%F %T %Z')"
