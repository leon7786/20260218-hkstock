#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

INDEX = Path('docs/index.html')
FUTUNN_URL = 'https://www.futunn.com/quote/hk/ipo'
TZ_UTC8 = timezone(timedelta(hours=8))
ETF_TYPES = {4}
UA = 'Mozilla/5.0'


def fetch_finished_items() -> list[dict]:
    html = urlopen(Request(FUTUNN_URL, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'}), timeout=30).read().decode('utf-8', 'ignore')
    obj = json.loads(re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S).group(1))
    return obj.get('ipo_finished_list', {}).get('list', [])


def fmt_date(ts: int | str | None) -> str:
    if not ts:
        return '—'
    return datetime.fromtimestamp(int(ts), tz=TZ_UTC8).strftime('%Y/%m/%d')


def fmt_num_text(s: str | None, digits: int = 1) -> str:
    if not s or str(s).strip() in {'', '--'}:
        return '—'
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s).replace(',', ''))
    if not m:
        return str(s)
    return f"{float(m.group(1)):.{digits}f}"


def fmt_pct_text(s: str | None, digits: int = 1) -> str:
    if not s or str(s).strip() in {'', '--'}:
        return '—'
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s))
    if not m:
        return str(s)
    return f"{float(m.group(1)):+.{digits}f}%".replace('+0.0%', '0.0%').replace('+0.00%', '0.00%')


def fmt_pct_plain(s: str | None, digits: int = 1) -> str:
    if not s or str(s).strip() in {'', '--'}:
        return '—'
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s))
    if not m:
        return str(s)
    return f"{float(m.group(1)):.{digits}f}%"


def parse_sort_num_from_pct(s: str | None) -> str:
    if not s or str(s).strip() in {'', '--'}:
        return ''
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s))
    return m.group(1) if m else ''


def parse_sort_num_from_textnum(s: str | None) -> str:
    if not s or str(s).strip() in {'', '--'}:
        return ''
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s).replace(',', ''))
    return m.group(1) if m else ''


def make_td(label: str, sort_value: str, display: str, sort_num: str | None = None, cls: str | None = None) -> str:
    attrs = []
    if cls:
        attrs.append(f'class="{cls}"')
    if label:
        attrs.append(f'data-col="{label}"')
    if sort_value is not None:
        attrs.append(f'data-sort="{sort_value}"')
    if sort_num not in (None, ''):
        attrs.append(f'data-sort-num="{sort_num}"')
    attr_text = ' '.join(attrs)
    return f'<td {attr_text}>{display}</td>'


def build_row(item: dict) -> str:
    code = str(item.get('stockCode', '')).zfill(5)
    name = str(item.get('name') or '—')
    listing_date = fmt_date(item.get('listingDate'))

    cum_raw = str(item.get('ipoPriceChangeRatio') or '—')
    price_raw = str(item.get('price') or '—')
    ipo_raw = str(item.get('ipoPrice') or '—')
    first_day_raw = str(item.get('firstDayPcr') or '—')
    dark_num_raw = str(item.get('darkChangeNum') or '—')
    dark_ratio_raw = str(item.get('darkChangeRatio') or '—')
    change_raw = str(item.get('changeRatio') or '—')
    rise_days_raw = str(item.get('continuousRiseDayCnt') or '—')
    volume_raw = str(item.get('tradeVolumn') or '—')

    tds = [
        make_td('上市日期', listing_date, listing_date),
        make_td('', code, code, cls='code'),
        make_td('', name, name, cls='name'),
        make_td('累计涨幅', cum_raw, fmt_pct_plain(cum_raw), parse_sort_num_from_pct(cum_raw)),
        make_td('中签率', '—', '—'),
        make_td('公开募资(倍)', '—', '—'),
        make_td('配售超购倍数', '—', '—'),
        make_td('公开发售超购倍数', '—', '—'),
        make_td('回拨', '—', '—'),
        make_td('绿鞋', '—', '—'),
        make_td('现价', price_raw, fmt_num_text(price_raw), parse_sort_num_from_textnum(price_raw)),
        make_td('公开募资', '—', '—'),
        make_td('国际发售', '—', '—'),
        make_td('首日涨幅', first_day_raw, fmt_pct_plain(first_day_raw), parse_sort_num_from_pct(first_day_raw)),
        make_td('暗盘涨跌额', dark_num_raw, fmt_num_text(dark_num_raw, 3), parse_sort_num_from_textnum(dark_num_raw)),
        make_td('暗盘涨跌幅', dark_ratio_raw, fmt_pct_plain(dark_ratio_raw), parse_sort_num_from_pct(dark_ratio_raw)),
        make_td('发行价', ipo_raw, fmt_num_text(ipo_raw), parse_sort_num_from_textnum(ipo_raw)),
        make_td('涨跌幅', change_raw, fmt_pct_plain(change_raw), parse_sort_num_from_pct(change_raw)),
        make_td('连涨天数', rise_days_raw, fmt_num_text(rise_days_raw), parse_sort_num_from_textnum(rise_days_raw)),
        make_td('成交量', volume_raw, volume_raw),
    ]
    return '<tr>' + ''.join(tds) + '</tr>'


def main() -> int:
    html = INDEX.read_text(encoding='utf-8')
    existing_codes = {c.zfill(5) for c in re.findall(r'<td class="code"[^>]*>(\d+)</td>', html)}
    items = fetch_finished_items()

    new_rows = []
    for item in items:
        code = str(item.get('stockCode', '')).zfill(5)
        if item.get('instrumentType') in ETF_TYPES:
            continue
        if code in existing_codes:
            continue
        new_rows.append((fmt_date(item.get('listingDate')), code, build_row(item)))

    new_rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    if not new_rows:
        print('no_new_rows')
        return 0

    m = re.search(r'(<tbody>)(.*?)(</tbody>)', html, re.S)
    if not m:
        raise SystemExit('tbody not found')
    body = m.group(2)
    merged = '\n'.join(row for _, _, row in new_rows) + '\n' + body.strip()
    new_html = html[:m.start(2)] + merged + html[m.end(2):]
    INDEX.write_text(new_html, encoding='utf-8')
    print('added_codes', [code for _, code, _ in new_rows])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
