#!/usr/bin/env python3
"""Fix docs/index.html table structure.

Problems observed:
- thead has 25 headers but tbody rows have 20 cells, breaking sorting.

User requests:
- 股票名称 move to the right of 代码
- 累计涨幅 move to the right of 股票名称
- Make sorting (esp. 配售超购倍数) reliable: requires header/cell alignment.

This script:
- Rebuilds thead to exactly match the 20 tbody columns.
- Reorders tbody columns into the requested order.

It does NOT invent data.
"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup


def main() -> int:
    path = Path("docs/index.html")
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    table = soup.select_one("table")
    thead = table.select_one("thead") if table else None
    tbody = table.select_one("tbody") if table else None
    if not table or not thead or not tbody:
        raise SystemExit("missing table/thead/tbody")

    first_tr = tbody.select_one("tr")
    if not first_tr:
        raise SystemExit("no rows")
    first_tds = first_tr.find_all("td", recursive=False)
    td_count = len(first_tds)
    if td_count != 20:
        raise SystemExit(f"unexpected td_count={td_count} (expected 20)")

    # Map current column positions by td metadata in first row
    col_names = []
    for td in first_tds:
        name = td.get("data-col")
        if not name:
            cls = td.get("class") or []
            if "code" in cls:
                name = "代码"
            elif "name" in cls:
                name = "股票名称"
        col_names.append(name)

    # Fallback: use existing thead first 20 headers if any td missing data-col
    if any(n is None for n in col_names):
        ths = thead.select("th")
        headers = [re.sub(r"[↕\s]+$", "", th.get_text(strip=True)).strip() for th in ths[:td_count]]
        col_names = [col_names[i] or headers[i] for i in range(td_count)]

    idx = {n: i for i, n in enumerate(col_names)}

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
        raise SystemExit(f"missing required columns in tbody mapping: {missing}\ncol_names={col_names}")

    order = [idx[h] for h in desired]

    # Rebuild THEAD: exactly 20 headers in desired order
    trh = thead.select_one("tr")
    if not trh:
        trh = soup.new_tag("tr")
        thead.append(trh)
    for th in list(trh.find_all("th", recursive=False)):
        th.extract()

    for i, name in enumerate(desired):
        th = soup.new_tag("th")
        th["data-index"] = str(i)
        th.string = name + " "
        arr = soup.new_tag("span")
        arr["class"] = "arrow"
        arr.string = "↕"
        th.append(arr)
        trh.append(th)

    # Reorder TBODY rows
    for tr in tbody.select("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != td_count:
            continue
        old = list(tds)
        for td in old:
            td.extract()
        for j in order:
            tr.append(old[j])

    path.write_text(str(soup), encoding="utf-8")
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
