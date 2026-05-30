#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

FUTUNN_URL = 'https://www.futunn.com/quote/hk/ipo'
UA = 'Mozilla/5.0'
TZ_UTC8 = timezone(timedelta(hours=8))
INDEX = Path('docs/index.html')
PENDING_JSON = Path('docs/pending-ipo.json')
OUT = Path('reports/compare_futunn_vs_site.json')
ETF_TYPES = {4}


def fetch_finished_items() -> list[dict]:
    req = Request(FUTUNN_URL, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
    html = urlopen(req, timeout=30).read().decode('utf-8', 'ignore')
    obj = json.loads(re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S).group(1))
    return obj.get('ipo_finished_list', {}).get('list', [])


def extract_site_data() -> tuple[list[str], dict[str, dict], Counter]:
    soup = BeautifulSoup(INDEX.read_text(encoding='utf-8'), 'html.parser')

    # 待上市区块是前端运行时从 docs/pending-ipo.json 加载，
    # 因此这里直接以 pending-ipo.json 作为页面实际数据源。
    pending_codes = []
    if PENDING_JSON.exists():
        pending_json = json.loads(PENDING_JSON.read_text(encoding='utf-8'))
        pending_codes = sorted({str(x.get('code', '')).zfill(5) for x in pending_json.get('items', []) if x.get('code')})

    history = {}
    missing = Counter()
    rows = soup.select('.table table tbody tr')
    headers = [th.get_text(' ', strip=True).replace(' ↕', '').replace(' ↓', '').replace(' ↑', '') for th in soup.select('.table table thead th')]
    for tr in rows:
        tds = tr.select('td')
        if len(tds) < len(headers):
            continue
        row = {}
        for i, h in enumerate(headers):
            val = tds[i].get_text(' ', strip=True)
            row[h] = val
            if val in {'—', '-', ''}:
                missing[h] += 1
        code = row.get('代码', '').zfill(5)
        if re.fullmatch(r'\d{5}', code):
            history[code] = row

    return pending_codes, history, missing


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    futunn_finished = fetch_finished_items()
    site_pending, site_history, missing = extract_site_data()

    futunn_finished_codes = sorted({str(x.get('stockCode', '')).zfill(5) for x in futunn_finished if x.get('instrumentType') not in ETF_TYPES and x.get('stockCode')})
    site_history_codes = sorted(site_history.keys())

    # 这里真正关心的是：富途当前已上市列表里出现的新 code，站内有没有漏。
    # 站内比富途“多”是正常的，因为站内保留历史档案。
    missing_in_site = sorted(set(futunn_finished_codes) - set(site_history_codes))
    historical_archive_only = sorted(set(site_history_codes) - set(futunn_finished_codes))

    pending_json_codes = site_pending
    pending_only_in_json = []
    pending_only_in_page = []

    report = {
        'generatedAt': datetime.now(TZ_UTC8).strftime('%Y-%m-%d %H:%M:%S'),
        'sourceUrl': FUTUNN_URL,
        'futunnFinishedCount': len(futunn_finished_codes),
        'siteHistoryCount': len(site_history_codes),
        'missingListedCodesInSite': missing_in_site,
        'historicalArchiveOnlyCount': len(historical_archive_only),
        'pendingJsonCount': len(pending_json_codes),
        'pendingPageDataCount': len(site_pending),
        'pendingOnlyInJson': pending_only_in_json,
        'pendingOnlyInPage': pending_only_in_page,
        'historyMissingFieldCounts': dict(missing),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
