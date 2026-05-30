#!/usr/bin/env python3
"""Fill remaining missing "中签率" and "配售超购倍数" from the web (Exa MCP).

This is the step after PDF filling:
- First run: fill_hit_and_placing_from_allotment_pdf.py
- Then run this script to fill the rest.

Safety / conservatism:
- Only overwrite placeholders (0.0% / 0.0倍 / 未知 / 待定 / —)
- Require identity check: (code present in page) OR (stock name token present)
- Require strong context patterns for placing oversub times to avoid reallocation ranges.

Requires:
- config/mcporter.json exists in repo (copied from workspace-leader)
- mcporter installed (global)

Usage:
  python3 scripts/fill_hit_and_placing_from_web.py --apply --limit 30 --report reports/hit_placing_web_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from bs4 import BeautifulSoup


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def is_missing_percent(s: str) -> bool:
    t = (s or "").strip()
    return t in ("", "—", "未知", "待定") or (t.startswith("0.0") and t.endswith("%"))


def is_missing_times(s: str) -> bool:
    t = (s or "").strip()
    return t in ("", "—", "未知", "待定") or (t.startswith("0.0") and t.endswith("倍"))


def mcp_call(cfg: Path, expr: str, timeout: int = 180) -> str:
    out = subprocess.check_output(
        ["mcporter", "--config", str(cfg), "call", expr],
        text=True,
        timeout=timeout,
        stderr=subprocess.STDOUT,
    )
    return out


def exa_search_urls(cfg: Path, query: str, n: int = 6) -> List[str]:
    expr = (
        'exa.web_search_exa(query: "' + query.replace('"', "\\\"") + f'", numResults: {n}, type: "fast")'
    )
    out = mcp_call(cfg, expr)
    urls = re.findall(r"URL:\s*(https?://\S+)", out)
    # de-dup preserve order
    seen = set()
    res = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            res.append(u)
    return res


def exa_crawl(cfg: Path, url: str, chars: int = 90000) -> str:
    expr = 'exa.crawling_exa(url: "' + url.replace('"', "\\\"") + f'", maxCharacters: {chars})'
    return mcp_call(cfg, expr, timeout=240)


def identity_ok(text: str, code: str, name: str) -> bool:
    t = text or ""
    if code and code in t:
        return True
    # loose: require at least 2-char token from name
    nm = (name or "").strip()
    if len(nm) >= 2 and nm[:2] in t:
        return True
    return False


def extract_one_lot_hit_rate(text: str) -> Optional[float]:
    c = re.sub(r"\s+", "", text or "")
    for pat in [
        r"一手(?:\([^\)]*\))?中籤率[^0-9]{0,30}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
        r"一手(?:\([^\)]*\))?中签率[^0-9]{0,30}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
        r"一手(?:\([^\)]*\))?獲配比率[^0-9]{0,30}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
        r"一手(?:\([^\)]*\))?获配比率[^0-9]{0,30}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
    ]:
        m = re.search(pat, c, flags=re.I)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
            except Exception:
                continue
            if 0 < v <= 100:
                return v
    return None


def extract_placing_times(text: str) -> Optional[float]:
    c = re.sub(r"\s+", "", text or "")
    # avoid range-only hits
    # (we still allow matches elsewhere)
    m = re.search(
        r"(國際發售|国际发售|國際配售|国际配售)[\s\S]{0,240}?(?:錄得|录得|認購倍數|认购倍数|超額認購|超额认购|超購|超购|認購水平|认购水平)[\s\S]{0,90}?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
        c,
        flags=re.I,
    )
    if m:
        try:
            v = float(m.group(2).replace(",", ""))
        except Exception:
            return None
        if 0 < v <= 5000:
            return v
    return None


def fmt_percent(v: float) -> str:
    return f"{v:.1f}%"


def fmt_times(v: float) -> str:
    return f"{v:.1f}倍"


@dataclass
class Item:
    code: str
    name: str
    hit_before: str
    placing_before: str
    hit_after: str
    placing_after: str
    hit_url: Optional[str] = None
    placing_url: Optional[str] = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=Path("docs/index.html"))
    ap.add_argument("--config", type=Path, default=Path("config/mcporter.json"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--report", type=Path, default=Path("reports/hit_placing_web_report.json"))
    args = ap.parse_args()

    if not args.config.exists():
        raise SystemExit(f"missing config: {args.config} (need Exa MCP config)")

    html = args.index.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead th")][:20]
    idx: Dict[str, int] = {h: i for i, h in enumerate(ths)}

    for need in ["代码", "股票名称", "中签率", "配售超购倍数"]:
        if need not in idx:
            raise SystemExit(f"missing column: {need}")

    code_i = idx["代码"]
    name_i = idx["股票名称"]
    hit_i = idx["中签率"]
    placing_i = idx["配售超购倍数"]

    attempted = 0
    updated = 0
    items: List[Item] = []

    for tr in soup.select("table tbody tr"):
        if updated >= args.limit:
            break
        tds = tr.find_all("td")
        if len(tds) != 20:
            continue

        code = tds[code_i].get_text(strip=True)
        name = tds[name_i].get_text(strip=True)
        hit_before = tds[hit_i].get_text(strip=True)
        placing_before = tds[placing_i].get_text(strip=True)

        need_hit = is_missing_percent(hit_before)
        need_placing = is_missing_times(placing_before)
        if not (need_hit or need_placing):
            continue

        attempted += 1

        q = f"{code} {name} 一手中籤率 國際發售 認購倍數 配發結果"
        urls = exa_search_urls(args.config, q, n=8)

        hit_v = None
        placing_v = None
        hit_url = None
        placing_url = None

        for u in urls:
            try:
                txt = exa_crawl(args.config, u)
            except Exception:
                continue
            if not identity_ok(txt, code, name):
                continue
            if need_hit and hit_v is None:
                v = extract_one_lot_hit_rate(txt)
                if v is not None:
                    hit_v = v
                    hit_url = u
            if need_placing and placing_v is None:
                v = extract_placing_times(txt)
                if v is not None:
                    placing_v = v
                    placing_url = u
            if (not need_hit or hit_v is not None) and (not need_placing or placing_v is not None):
                break

        hit_after = hit_before
        placing_after = placing_before
        changed = False

        if hit_v is not None:
            hit_after = fmt_percent(hit_v)
            changed = True
            if args.apply:
                tds[hit_i].string = hit_after

        if placing_v is not None:
            placing_after = fmt_times(placing_v)
            changed = True
            if args.apply:
                tds[placing_i].string = placing_after

        if changed:
            updated += 1

        items.append(
            Item(
                code=code,
                name=name,
                hit_before=hit_before,
                placing_before=placing_before,
                hit_after=hit_after,
                placing_after=placing_after,
                hit_url=hit_url,
                placing_url=placing_url,
            )
        )

    args.report.parent.mkdir(exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "attempted": attempted,
                "updated": updated,
                "items": [asdict(x) for x in items],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if args.apply:
        args.index.write_text(str(soup), encoding="utf-8")

    print(f"attempted={attempted} updated={updated} report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
