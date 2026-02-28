#!/usr/bin/env python3
"""Reorder columns in docs/index.html.

User request:
- 股票名称 移动到 代码 的右边
- 累计涨幅 移动到 股票名称 右边
- Fix sorting issues by keeping header count == row cell count and reindexing th[data-index].

This script does not change data, only reorders columns.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def main() -> int:
    path = Path("docs/index.html")
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    table = soup.select_one("table")
    if not table:
        raise SystemExit("no table")

    thead = table.select_one("thead")
    tbody = table.select_one("tbody")
    if not thead or not tbody:
        raise SystemExit("missing thead/tbody")

    ths = thead.select("th")
    if not ths:
        raise SystemExit("no headers")

    # Determine how many columns actually exist in rows (use first row)
    first_tr = tbody.select_one("tr")
    if not first_tr:
        raise SystemExit("no rows")
    td_count = len(first_tr.find_all("td", recursive=False))

    # Build header list but only keep first td_count headers to avoid mismatch
    ths = ths[:td_count]

    headers = [norm_header(th.get_text(strip=True)) for th in ths]
    idx = {h: i for i, h in enumerate(headers)}

    desired = [
        "上市日期",
        "代码",
        "股票名称",
        "累计涨幅",
        "中签率",
        "散户募资金额",
        "配售超购倍数",
        "公开发售超购倍数",
        "回拨",
        "绿鞋",
        "价格",
        "公开募资",
        "国际发售",
        "首日涨幅",
        "暗盘涨跌额",
        "暗盘涨跌幅",
        "发行价",
        "涨跌幅",
        "连涨天数",
        "成交量",
    ]

    missing = [h for h in desired if h not in idx]
    if missing:
        raise SystemExit(f"missing headers in current table: {missing}")

    order = [idx[h] for h in desired]

    # Rebuild thead row: remove ALL existing headers, then insert exactly td_count headers
    trh = thead.select_one("tr")
    for th in list(trh.select("th")):
        th.extract()

    new_ths = [ths[i] for i in order]
    for new_i, th in enumerate(new_ths):
        th["data-index"] = str(new_i)
        # ensure arrow span exists
        arr = th.select_one(".arrow")
        if not arr:
            sp = soup.new_tag("span")
            sp["class"] = "arrow"
            sp.string = "↕"
            th.append(" ")
            th.append(sp)
        trh.append(th)

    # Reorder each row
    for tr in tbody.select("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != td_count:
            continue
        old = list(tds)
        for td in old:
            td.extract()
        for i in order:
            tr.append(old[i])

    path.write_text(str(soup), encoding="utf-8")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
