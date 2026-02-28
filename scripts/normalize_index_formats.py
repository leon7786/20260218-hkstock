#!/usr/bin/env python3
"""Normalize formats in docs/index.html.

User requirements:
- 散户募资金额：小于 1 亿港元，用“xxxx万港元”表示，且为整数万（不保留小数）。
- 配售超购倍数：保留 1 位小数。
- 公开发售超购倍数：保留 1 位小数。
- 公开募资、国际发售：保留 1 位小数（当前为“x.x 港元”，此脚本把它规范成 万/亿港元 并保留 1 位小数）。

This script does not invent new data; it only reformats existing cells.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def parse_hkd_amount(s: str) -> Optional[float]:
    t = (s or "").strip().replace(" ", "")
    if not t or t == "—" or "待定" in t or "未知" in t:
        return None
    # already 亿/万/百万
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)亿港元$", t)
    if m:
        return float(m.group(1)) * 1e8
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)万港元$", t)
    if m:
        return float(m.group(1)) * 1e4
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)百万港元$", t)
    if m:
        return float(m.group(1)) * 1e6
    # raw HKD
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)港元$", t)
    if m:
        return float(m.group(1))
    return None


def fmt_hkd(hkd: float, *, retail: bool = False, one_decimal: bool = True) -> str:
    if hkd is None:
        return "—"
    if hkd == 0:
        return "0港元"

    if hkd < 1e8:
        # show as integer 万 for retail
        v = hkd / 1e4
        if retail:
            return f"{int(round(v))}万港元"
        if one_decimal:
            # hide trailing .0
            if abs(v - round(v)) < 1e-9:
                return f"{int(round(v))}万港元"
            return f"{v:.1f}万港元"
        return f"{int(round(v))}万港元"

    v = hkd / 1e8
    if one_decimal:
        if abs(v - round(v)) < 1e-9:
            return f"{int(round(v))}亿港元"
        return f"{v:.1f}亿港元"
    return f"{v:.2f}亿港元"


def parse_times(s: str) -> Optional[float]:
    t = (s or "").strip()
    if not t or t == "—":
        return None
    t = t.replace("倍", "")
    try:
        return float(t)
    except Exception:
        return None


def fmt_times(v: float) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}倍"


def main() -> int:
    index = Path("docs/index.html")
    soup = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser")

    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead tr th")]
    # rows have only first 20 columns
    ths = ths[:20]
    idx = {h: i for i, h in enumerate(ths)}

    # required columns
    for col in ["散户募资金额", "配售超购倍数", "公开发售超购倍数", "公开募资", "国际发售"]:
        if col not in idx:
            raise SystemExit(f"missing col {col}")

    ret_i = idx["散户募资金额"]
    place_i = idx["配售超购倍数"]
    pub_i = idx["公开发售超购倍数"]
    pubfund_i = idx["公开募资"]
    intl_i = idx["国际发售"]

    changed = 0

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) <= max(ret_i, place_i, pub_i, pubfund_i, intl_i):
            continue

        # retail amount
        hkd = parse_hkd_amount(tds[ret_i].get_text(strip=True))
        if hkd is not None:
            new = fmt_hkd(hkd, retail=True)
            if tds[ret_i].get_text(strip=True) != new:
                tds[ret_i].string = new
                changed += 1
            tds[ret_i]["data-sort-num"] = f"{hkd:.0f}"
            tds[ret_i]["data-sort"] = new
            tds[ret_i].attrs.pop("title", None)

        # public募资 / intl募资
        for i in [pubfund_i, intl_i]:
            hkd = parse_hkd_amount(tds[i].get_text(strip=True))
            if hkd is not None:
                new = fmt_hkd(hkd, retail=False, one_decimal=True)
                if tds[i].get_text(strip=True) != new:
                    tds[i].string = new
                    changed += 1
                tds[i]["data-sort-num"] = f"{hkd:.0f}"
                tds[i]["data-sort"] = new
                tds[i].attrs.pop("title", None)

        # oversub times
        for i in [place_i, pub_i]:
            v = parse_times(tds[i].get_text(strip=True))
            if v is not None:
                new = fmt_times(v)
                if tds[i].get_text(strip=True) != new:
                    tds[i].string = new
                    changed += 1
                tds[i]["data-sort-num"] = f"{v:.6f}"
                tds[i]["data-sort"] = new
                tds[i].attrs.pop("title", None)

    index.write_text(str(soup), encoding="utf-8")
    print(f"changed_cells={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
