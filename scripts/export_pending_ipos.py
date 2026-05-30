#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

FUTUNN_URL = 'https://www.futunn.com/quote/hk/ipo'
OUT = Path('docs/pending-ipo.json')
TZ_UTC8 = timezone(timedelta(hours=8))
ETF_TYPES = {4}
UA = 'Mozilla/5.0'


def fetch_state() -> dict:
    req = Request(
        FUTUNN_URL,
        headers={
            'User-Agent': UA,
            'Accept': 'text/html,application/xhtml+xml',
        },
    )
    html = urlopen(req, timeout=30).read().decode('utf-8', 'ignore')
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S)
    if not m:
        raise SystemExit('window.__INITIAL_STATE__ not found')
    return json.loads(m.group(1))


def today_start_ts() -> int:
    now = datetime.now(TZ_UTC8)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp())


def normalize_item(item: dict, source: str) -> dict:
    return {
        'code': str(item.get('stockCode', '')).zfill(5),
        'name': str(item.get('name') or '—'),
        'price': item.get('price') or '—',
        'firstDayPcr': item.get('firstDayPcr') or '—',
        'darkChangeNum': item.get('darkChangeNum') or '—',
        'darkChangeRatio': item.get('darkChangeRatio') or '—',
        'ipoPriceChangeRatio': item.get('ipoPriceChangeRatio') or '—',
        'ipoPrice': item.get('ipoPrice') or '—',
        'changeRatio': item.get('changeRatio') or '—',
        'tradeVolumn': item.get('tradeVolumn') or '—',
        'tradeTrunover': item.get('tradeTrunover') or '—',
        'tradeChangeraio': item.get('tradeChangeraio') or '—',
        'peLyr': item.get('peLyr') or '—',
        'marketVal': item.get('marketVal') or '—',
        'totalShares': item.get('totalShares') or '—',
        'listingDateTs': int(item.get('listingDate') or 0),
        'listingDate': (
            datetime.fromtimestamp(int(item.get('listingDate') or 0), tz=TZ_UTC8).strftime('%Y/%m/%d')
            if item.get('listingDate')
            else '—'
        ),
        'instrumentType': item.get('instrumentType'),
        'marketLabel': item.get('marketLabel') or 'HK',
        'sourceBucket': source,
    }


def build_payload() -> dict:
    state = fetch_state()
    pending_floor = today_start_ts()

    combined: dict[str, dict] = {}
    source_counts = {}

    for source_key in ('ipo_applying_list', 'ipo_finished_list'):
        raw_list = state.get(source_key, {}).get('list', [])
        source_counts[source_key] = len(raw_list)
        for raw in raw_list:
            code = str(raw.get('stockCode', '')).zfill(5)
            if not code or raw.get('instrumentType') in ETF_TYPES:
                continue
            listing_ts = int(raw.get('listingDate') or 0)
            if listing_ts < pending_floor:
                continue
            combined[code] = normalize_item(raw, source_key)

    items = sorted(combined.values(), key=lambda x: (x['listingDateTs'], x['code']))
    generated_at = datetime.now(TZ_UTC8).strftime('%Y/%m/%d %H:%M:%S')

    return {
        'generatedAt': generated_at,
        'timezone': 'Asia/Shanghai',
        'sourceUrl': FUTUNN_URL,
        'notes': [
            '数据来源为富途新股页面 window.__INITIAL_STATE__。',
            '优先合并 ipo_applying_list，同时补充 ipo_finished_list 中上市日期 >= 今日(UTC+8) 的条目。',
            '已排除 ETF。',
        ],
        'todayFloor': datetime.fromtimestamp(pending_floor, tz=TZ_UTC8).strftime('%Y/%m/%d 00:00:00'),
        'sourceCounts': source_counts,
        'count': len(items),
        'items': items,
    }


def main() -> int:
    payload = build_payload()
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f"wrote {OUT} count={payload['count']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
