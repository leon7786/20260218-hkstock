#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

INDEX = Path('docs/index.html')
FUTUNN_URL = 'https://www.futunn.com/quote/hk/ipo'
UA = 'Mozilla/5.0'
TZ_UTC8 = timezone(timedelta(hours=8))


def fetch_finished_raw_count() -> int | None:
    html = urlopen(Request(FUTUNN_URL, headers={'User-Agent': UA}), timeout=30).read().decode('utf-8', 'ignore')
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S)
    if not m:
        return None
    obj = json.loads(m.group(1))
    return len(obj.get('ipo_finished_list', {}).get('list', []))


def main() -> int:
    soup = BeautifulSoup(INDEX.read_text(encoding='utf-8'), 'html.parser')
    metas = soup.select('div.meta')
    if len(metas) < 2:
        raise SystemExit('expected at least two .meta blocks in docs/index.html')

    filtered_count = len(soup.select('.table table tbody tr'))
    raw_count = fetch_finished_raw_count()
    now_str = datetime.now(TZ_UTC8).strftime('%Y/%m/%d %H:%M:%S')

    source_link = '<a href="https://www.futunn.com/quote/hk/ipo" style="color:#93c5fd" target="_blank">https://www.futunn.com/quote/hk/ipo</a>'
    raw_txt = str(raw_count) if raw_count is not None else '—'
    metas[1].clear()
    metas[1].append(BeautifulSoup(
        f'来源：{source_link} ｜ 抓取时间：{now_str} ｜ 抓取页数：1 ｜ 原始条目：{raw_txt} ｜ 过滤后：{filtered_count} ｜ 建档目录：archive/&lt;code&gt;/summary.json',
        'html.parser'
    ))

    INDEX.write_text(str(soup), encoding='utf-8')
    print(json.dumps({
        'updated': True,
        'generatedAt': now_str,
        'rawCount': raw_count,
        'filteredCount': filtered_count,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
