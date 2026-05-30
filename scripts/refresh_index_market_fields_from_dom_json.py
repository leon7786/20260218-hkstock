#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from bs4 import BeautifulSoup

INDEX = Path('docs/index.html')
DOM_JSON = Path('reports/futunn_finished_dom.json')


def fmt_num_text(s: str | None, digits: int = 1) -> str:
    if s is None or str(s).strip() in {'', '--'}:
        return '—'
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s).replace(',', ''))
    if not m:
        return str(s)
    return f"{float(m.group(1)):.{digits}f}"


def fmt_pct_plain(s: str | None, digits: int = 1) -> str:
    if s is None or str(s).strip() in {'', '--'}:
        return '—'
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s))
    if not m:
        return str(s)
    return f"{float(m.group(1)):.{digits}f}%"


def parse_sort_num(s: str | None) -> str:
    if s is None or str(s).strip() in {'', '--'}:
        return ''
    m = re.search(r'([+-]?\d+(?:\.\d+)?)', str(s).replace(',', ''))
    return m.group(1) if m else ''


def set_cell(td, raw: str | None, display: str, numeric: bool = True):
    raw_text = '—' if raw is None or str(raw).strip() in {'', '--'} else str(raw)
    td['data-sort'] = raw_text
    sort_num = parse_sort_num(raw_text) if numeric else ''
    if sort_num:
        td['data-sort-num'] = sort_num
    elif td.has_attr('data-sort-num'):
        del td['data-sort-num']
    td.clear()
    td.append(display)


def main() -> int:
    data = json.loads(DOM_JSON.read_text(encoding='utf-8'))
    items = {str(x.get('code', '')).zfill(5): x for x in data.get('items', [])}
    soup = BeautifulSoup(INDEX.read_text(encoding='utf-8'), 'html.parser')
    changed = []

    for tr in soup.select('tbody tr'):
        code_td = tr.select_one('td.code')
        if not code_td:
            continue
        code = code_td.get_text(' ', strip=True).zfill(5)
        item = items.get(code)
        if not item:
            continue
        td_by_col = {td.get('data-col'): td for td in tr.select('td[data-col]')}
        mapping = {
            '累计涨幅': (item.get('ipoPriceChangeRatio'), fmt_pct_plain(item.get('ipoPriceChangeRatio'))),
            '现价': (item.get('price'), fmt_num_text(item.get('price'))),
            '首日涨幅': (item.get('firstDayPcr'), fmt_pct_plain(item.get('firstDayPcr'))),
            '暗盘涨跌额': (item.get('darkChangeNum'), fmt_num_text(item.get('darkChangeNum'), 3)),
            '暗盘涨跌幅': (item.get('darkChangeRatio'), fmt_pct_plain(item.get('darkChangeRatio'))),
            '发行价': (item.get('ipoPrice'), fmt_num_text(item.get('ipoPrice'))),
            '涨跌幅': (item.get('changeRatio'), fmt_pct_plain(item.get('changeRatio'))),
            '连涨天数': (item.get('continuousRiseDayCnt'), fmt_num_text(item.get('continuousRiseDayCnt'))),
            '成交量': (item.get('tradeVolumn'), str(item.get('tradeVolumn') or '—')),
        }
        row_changes = {}
        for col, (raw, display) in mapping.items():
            td = td_by_col.get(col)
            if not td:
                continue
            before = td.get_text(' ', strip=True)
            if before != display:
                row_changes[col] = {'from': before, 'to': display}
            set_cell(td, raw, display, numeric=(col != '成交量'))
        if row_changes:
            name_td = tr.select_one('td.name')
            changed.append({'code': code, 'name': name_td.get_text(' ', strip=True) if name_td else '', 'changes': row_changes})

    INDEX.write_text(str(soup), encoding='utf-8')
    print(json.dumps({'changedCount': len(changed), 'sample': changed[:30]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
