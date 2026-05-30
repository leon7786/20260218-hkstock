#!/usr/bin/env bash
# Telegram dark session IPO notification
set -euo pipefail

ROOT=/root/Project/*20260527-hkstock-futu
ENV_FILE="$ROOT/env"
cd "$ROOT"
mkdir -p logs

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: missing env file: $ENV_FILE" >&2
  exit 1
fi

mapfile -t env_values < <(python3 - <<'PY'
from pathlib import Path
import re

path = Path('/root/Project/*20260527-hkstock-futu/env')
lines = [line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
token = ''
chat_id = ''
for line in lines:
    if line.startswith('TG_BOT_TOKEN='):
        token = line.split('=', 1)[1].strip().strip('"\'')
    elif line.startswith('TG_CHAT_ID='):
        chat_id = line.split('=', 1)[1].strip().strip('"\'')
if not token:
    token = next((line for line in lines if ':' in line and not line.lower().startswith('bot')), '')
if not chat_id:
    if 'id' in lines and lines.index('id') + 1 < len(lines):
        chat_id = lines[lines.index('id') + 1]
    else:
        chat_id = next((line for line in lines if re.fullmatch(r'-?\d+', line)), '')
if not token or not chat_id:
    raise SystemExit('failed to parse TG_BOT_TOKEN/TG_CHAT_ID from env')
print(token)
print(chat_id)
PY
)

export TG_BOT_TOKEN="${env_values[0]}"
export TG_CHAT_ID="${env_values[1]}"
export HTTPS_PROXY=http://admin12:Dd%3B%272131801a@127.0.0.1:2002
export HTTP_PROXY=http://admin12:Dd%3B%272131801a@127.0.0.1:2002
export PLAYWRIGHT_PROXY="http://127.0.0.1:2002|admin12|Dd;'2131801a"

python3 scripts/notify_dark_session_tg.py --recent-days 5 2>&1 | tee -a logs/notify_tg.log