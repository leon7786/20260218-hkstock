#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
PENDING_JSON = ROOT / "docs" / "pending-ipo.json"
DARK_RE = re.compile(r"(20\d{2}/\d{1,2}/\d{1,2})\s+(\d{2}:\d{2})~(\d{2}:\d{2})")
WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
HK_TZ = datetime.now(UTC).astimezone().tzinfo
try:
    from zoneinfo import ZoneInfo
    HK_TZ = ZoneInfo("Asia/Hong_Kong")
except Exception:
    pass


def run_pending_sync() -> None:
    subprocess.run(["npm", "run", "sync:pending-ipo"], cwd=ROOT, check=True)


def hk_now() -> datetime:
    return datetime.now(HK_TZ)


def parse_dark_field(value: str) -> tuple[date, str, str] | None:
    m = DARK_RE.search(value.strip())
    if not m:
        return None
    dark_date = datetime.strptime(m.group(1), "%Y/%m/%d").date()
    return dark_date, m.group(2), m.group(3)


def collect_dark_entries(items: list[dict]) -> list[dict]:
    out: list[dict] = []
    for item in items:
        fields = item.get("fields") or []
        dark_field = fields[5] if len(fields) > 5 else ""
        if not isinstance(dark_field, str):
            continue
        parsed = parse_dark_field(dark_field)
        if not parsed:
            continue
        dark_date, dark_start, dark_end = parsed
        out.append(
            {
                "code": str(item.get("code") or "").zfill(5),
                "name": str(item.get("name") or ""),
                "dark": dark_field,
                "dark_date": dark_date,
                "dark_start": dark_start,
                "dark_end": dark_end,
                "listing": fields[6] if len(fields) > 6 else "—",
                "price": fields[0] if len(fields) > 0 else "—",
                "min_buy": fields[1] if len(fields) > 1 else "—",
            }
        )
    out.sort(key=lambda x: (x["dark_date"], x["dark_start"], x["code"]))
    return out


def pick_today_1615(entries: list[dict], today: date) -> list[dict]:
    return [x for x in entries if x["dark_date"] == today and x["dark_start"] == "16:15"]


def pick_recent(entries: list[dict], today: date, days: int) -> list[dict]:
    end = today + timedelta(days=max(days, 0))
    return [x for x in entries if today <= x["dark_date"] <= end]


def format_date_with_weekday(d: date) -> str:
    return f"{d.strftime('%Y/%m/%d')}（{WEEKDAY_ZH[d.weekday()]}）"


def build_message(today_hits: list[dict], recent: list[dict], generated_at: str, recent_days: int) -> str:
    now_text = hk_now().strftime("%Y/%m/%d %H:%M")
    lines = [f"【暗盘提醒】{now_text}"]

    lines.append(f"今日 16:15 暗盘开盘：{len(today_hits)} 只")
    for x in today_hits:
        lines.append(
            f"- {x['code']} {x['name']}｜暗盘 {x['dark']}｜招股价 {x['price']}｜入场 {x['min_buy']}｜上市 {x['listing']}"
        )

    lines.append("")
    lines.append(f"最近{recent_days}天暗盘日程（含今天）")
    if not recent:
        lines.append("- 无")
    else:
        current = None
        for x in recent:
            d = x["dark_date"]
            if d != current:
                current = d
                lines.append(format_date_with_weekday(d))
            lines.append(f"- {x['code']} {x['name']}｜{x['dark_start']}~{x['dark_end']}")

    lines.append("")
    lines.append(f"更新时间：{generated_at}")
    return "\n".join(lines)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = f"chat_id={quote_plus(chat_id)}&text={quote_plus(text)}"
    req = Request(
        url,
        data=data.encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8", "ignore"))
    if not payload.get("ok"):
        raise SystemExit(f"telegram send failed: {payload}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Notify Telegram for 16:15 dark session IPOs")
    parser.add_argument("--recent-days", type=int, default=5, help="Include schedule in [today, today+N days]")
    parser.add_argument("--skip-sync", action="store_true", help="Do not refresh pending-ipo.json before checking")
    parser.add_argument("--force-send", action="store_true", help="Send even when no today 16:15 matches")
    args = parser.parse_args()

    token = os.environ.get("TG_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TG_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("TG_BOT_TOKEN or TG_CHAT_ID is missing")

    if not args.skip_sync:
        run_pending_sync()

    data = json.loads(PENDING_JSON.read_text(encoding="utf-8"))
    items = data.get("items") or []
    generated_at = str(data.get("generatedAt") or "—")

    today = hk_now().date()
    entries = collect_dark_entries(items)
    today_hits = pick_today_1615(entries, today)
    recent = pick_recent(entries, today, args.recent_days)

    if not today_hits and not args.force_send:
        print("skip telegram: no today 16:15 dark session IPO")
        return 0

    text = build_message(today_hits, recent, generated_at, args.recent_days)
    send_telegram(token, chat_id, text)
    print(f"sent telegram, today_hits={len(today_hits)}, recent={len(recent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
