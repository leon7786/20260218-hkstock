#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

INDEX = Path('docs/index.html')
DOCS = Path('docs')
FUTUNN_URL = 'https://www.futunn.com/quote/hk/ipo'
UA = 'Mozilla/5.0'

BAD_NAME_RE = re.compile(r'^\s*[+-]?\d+(?:\.\d+)?%\s*$')


def fetch_futunn_names() -> dict[str, str]:
    html = urlopen(Request(FUTUNN_URL, headers={'User-Agent': UA}), timeout=30).read().decode('utf-8', 'ignore')
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.S)
    if not m:
        return {}
    obj = json.loads(m.group(1))
    out: dict[str, str] = {}
    for bucket in ('ipo_finished_list', 'ipo_applying_list'):
        for item in obj.get(bucket, {}).get('list', []):
            code = str(item.get('stockCode', '')).zfill(5)
            name = str(item.get('name') or '').strip()
            if code and name:
                out[code] = name
    return out


def readme_name_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for d in DOCS.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r'^(\d{5})\s+(.+)$', d.name)
        if not m:
            continue
        code, name = m.group(1), m.group(2).strip()
        if code and name:
            out[code] = name
    return out


def is_bad_name(name: str) -> bool:
    name = (name or '').strip()
    return not name or BAD_NAME_RE.fullmatch(name) is not None


def main() -> int:
    soup = BeautifulSoup(INDEX.read_text(encoding='utf-8'), 'html.parser')
    futunn = fetch_futunn_names()
    readmes = readme_name_map()
    fixed = []

    for tr in soup.select('table tbody tr'):
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 3:
            continue
        code_td = tds[1]
        name_td = tds[2]
        code = code_td.get_text(' ', strip=True).zfill(5)
        current = name_td.get_text(' ', strip=True)
        if not re.fullmatch(r'\d{5}', code):
            continue
        if not is_bad_name(current):
            continue
        replacement = futunn.get(code) or readmes.get(code)
        if not replacement or is_bad_name(replacement):
            continue
        name_td.string = replacement
        classes = set(name_td.get('class', []))
        classes.add('name')
        name_td['class'] = sorted(classes)
        name_td['data-sort'] = replacement
        fixed.append({'code': code, 'from': current, 'to': replacement})

    INDEX.write_text(str(soup), encoding='utf-8')
    print(json.dumps({'fixedCount': len(fixed), 'fixed': fixed[:80]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
