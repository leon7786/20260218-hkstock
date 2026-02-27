#!/usr/bin/env python3
"""Fill missing fields in docs/index.html by *web search* (DuckDuckGo HTML) with low concurrency.

User requirement:
- If PDF can't provide values, use full-web search to fill missing values in index.html.
- Keep concurrency low to avoid network rate limits.

What it fills (only when cell is missing or obviously invalid):
- 中签率 (one-lot hit rate) -> keep 1 decimal, percent
- 散户募资金额 (retail fundraising amount) -> HKD, formatted as 万/亿港元
- 配售超购倍数 (placing oversub, i.e. International Offering oversubscription) -> 2 decimals + 倍
- 公开发售超购倍数 (public oversub, i.e. Hong Kong Public Offering oversub) -> 2 decimals + 倍

Safety/conservatism:
- Only accept a candidate value if the web page contains the stock code OR issuer name.
- Only accept a value if the keyword context matches (e.g. 一手 near %, 公开发售 near 倍, 国际发售 near 倍).

Outputs:
- reports/web_fill_report.json (forced-add if you commit)

Usage:
  python3 scripts/fill_index_from_web.py --sleep 0.8 --max-results 4
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

from firecrawl_client import search as firecrawl_search


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def is_missing_text(s: str) -> bool:
    return (s or "").strip() in ("", "—")


def parse_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def fmt_percent(v: float) -> str:
    return f"{v:.1f}%"


def fmt_times(v: float) -> str:
    return f"{v:.2f}倍"


def parse_money_to_hkd(s: str) -> Optional[float]:
    t = (s or "").strip().replace(" ", "")
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿|億|万|萬)港元", t)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = m.group(2)
    if unit in ("亿", "億"):
        return v * 1e8
    if unit in ("万", "萬"):
        return v * 1e4
    return None


def fmt_hkd_amount(hkd: float) -> str:
    if hkd <= 0:
        return "0.0 港元"
    if hkd >= 1e8:
        v = hkd / 1e8
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{s}亿港元"
    v = hkd / 1e4
    if abs(v - round(v)) < 0.05:
        return f"{int(round(v))}万港元"
    return f"{v:.1f}万港元"


def ddg_search(query: str, max_results: int = 4, timeout: int = 30) -> List[Tuple[str, str]]:
    """DuckDuckGo search (DEPRECATED).

    This environment frequently receives HTTP 202 challenge pages from DDG.
    Keep the function for compatibility, but always return empty to hard-disable DDG.
    """

    return []


def bing_search(query: str, max_results: int = 4, timeout: int = 30) -> List[Tuple[str, str]]:
    # Use international bing to avoid some regional weirdness.
    url = f"https://www.bing.com/search?q={quote_plus(query)}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    out: List[Tuple[str, str]] = []
    for a in soup.select("li.b_algo h2 a"):
        href = a.get("href")
        title = a.get_text(strip=True)
        if not href:
            continue
        out.append((href, title))
        if len(out) >= max_results:
            break
    return out


def fetch_text(url: str, timeout: int = 30) -> str:
    """Fetch page text via requests+BeautifulSoup.

    NOTE: We intentionally do NOT use Firecrawl scrape here because it may return 402
    (Payment Required) in this environment.
    """

    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except requests.exceptions.SSLError:
        return ""
    except Exception:
        return ""

    if r.status_code != 200:
        return ""

    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def identity_ok(page_text: str, code5: str, name: str) -> bool:
    if not page_text:
        return False
    if code5 in page_text:
        return True
    # name gate: chinese 2 chars ok; english require 4
    n = (name or "").strip()
    if not n:
        return False
    is_ascii = sum(1 for ch in n if ord(ch) < 128) / max(1, len(n)) > 0.9
    if is_ascii:
        return n[:4].upper() in page_text.upper()
    return n[:2] in page_text


@dataclass
class Found:
    hit_rate: Optional[float] = None
    retail_hkd: Optional[float] = None
    public_times: Optional[float] = None
    placing_times: Optional[float] = None


def extract_from_page(text: str) -> Found:
    f = Found()
    if not text:
        return f

    compact = re.sub(r"\s+", "", text)

    # hit rate: require 一手 near percent
    m = re.search(r"一手[^%]{0,20}?([0-9]+(?:\.[0-9]+)?)%", compact)
    if m:
        v = parse_float(m.group(1))
        if v is not None and 0 <= v <= 100:
            f.hit_rate = v

    # retail amount: require 香港公开发售 + (募资/集资/筹资) + amount
    m = re.search(
        r"香港公開發售[\s\S]{0,80}?(?:募資|募集|集資|筹资|籌資)[\s\S]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿|億|万|萬)港元",
        compact,
    )
    if m:
        v = parse_float(m.group(1))
        if v is not None:
            f.retail_hkd = v * (1e8 if m.group(2) in ("亿", "億") else 1e4)

    # public oversub
    m = re.search(r"(?:香港)?公開發售[\s\S]{0,120}?(?:超額認購|超购|超購|認購水平)[\s\S]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)倍", compact)
    if m:
        v = parse_float(m.group(1))
        if v is not None and 0 <= v < 100000:
            f.public_times = v

    # placing oversub (international)
    # Accept a few common wordings, including "國際發售部份認購額0.93倍".
    m = re.search(
        r"(?:國際發售|国际发售|國際配售|国际配售|InternationalOffering)[\s\S]{0,240}?(?:超額認購|超购|超購|認購水平|認購額|认购额|认购倍数|認購倍數)[\s\S]{0,120}?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
        compact,
        flags=re.IGNORECASE,
    )
    if not m:
        # common phrasing on news sites
        m = re.search(r"國際配售[^0-9]{0,120}?(?:认购倍数|認購倍數|认购)[^0-9]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)倍", compact)
    if not m:
        m = re.search(r"國際發售[^0-9]{0,120}?(?:认购倍数|認購倍數|认购)[^0-9]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)倍", compact)
    if not m:
        m = re.search(r"國際發售部份認購額([0-9][0-9,]*(?:\.[0-9]+)?)倍", compact)
    if m:
        v = parse_float(m.group(1))
        if v is not None and 0 <= v < 100000:
            f.placing_times = v

    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--limit", type=int, default=9999)
    ap.add_argument("--sleep", type=float, default=0.8)
    ap.add_argument("--max-results", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    docs = repo / "docs"
    index_path = docs / "index.html"
    reports = repo / "reports"
    reports.mkdir(exist_ok=True)

    soup = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead tr th")]
    idx = {h: i for i, h in enumerate(ths)}

    need_cols = {
        "代码": 1,
        "股票名称": idx.get("股票名称"),
        "中签率": idx.get("中签率"),
        "散户募资金额": idx.get("散户募资金额"),
        "配售超购倍数": idx.get("配售超购倍数"),
        "公开发售超购倍数": idx.get("公开发售超购倍数"),
    }
    if any(need_cols[k] is None for k in ("股票名称", "中签率", "散户募资金额", "配售超购倍数", "公开发售超购倍数")):
        raise SystemExit(f"missing columns: {need_cols}")

    updated_rows = 0
    updated_cells = 0
    attempted_rows = 0
    items = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        # Some rows may have fewer cells (e.g. hidden columns). Only require needed columns.
        needed_max = max(
            need_cols["股票名称"],
            need_cols["中签率"],
            need_cols["散户募资金额"],
            need_cols["配售超购倍数"],
            need_cols["公开发售超购倍数"],
        )
        if len(tds) <= needed_max:
            continue

        code5 = tds[need_cols["代码"]].get_text(strip=True).zfill(5)
        name = tds[need_cols["股票名称"]].get_text(strip=True)

        miss = {
            "hit": is_missing_text(tds[need_cols["中签率"]].get_text(strip=True)),
            "retail": is_missing_text(tds[need_cols["散户募资金额"]].get_text(strip=True)),
            "place": is_missing_text(tds[need_cols["配售超购倍数"]].get_text(strip=True)),
            "public": is_missing_text(tds[need_cols["公开发售超购倍数"]].get_text(strip=True)),
        }

        if not any(miss.values()):
            continue

        attempted_rows += 1
        if attempted_rows > args.limit:
            break

        query = f"{code5} {name} 一手中签率 公開發售 超額認購 國際發售 配發結果"

        # Prefer Firecrawl search (more stable than DDG in this environment)
        hits: List[Tuple[str, str]] = []
        try:
            fc_hits = firecrawl_search(query, limit=args.max_results, lang="zh", country="hk")
            hits = [(h.url, h.title) for h in fc_hits if h.url]
        except Exception:
            hits = []

        time.sleep(args.sleep)

        if not hits:
            # fallback to Bing SERP parse
            hits = bing_search(query, max_results=max(2, args.max_results))
            time.sleep(args.sleep)

        found = Found()
        used = []

        for url, title in hits:
            page_text = fetch_text(url)
            time.sleep(args.sleep)
            if not identity_ok(page_text, code5, name):
                continue
            f = extract_from_page(page_text)
            if any([f.hit_rate, f.retail_hkd, f.public_times, f.placing_times]):
                used.append({"url": url, "title": title, "found": f.__dict__})
            # merge
            if found.hit_rate is None and f.hit_rate is not None:
                found.hit_rate = f.hit_rate
            if found.retail_hkd is None and f.retail_hkd is not None:
                found.retail_hkd = f.retail_hkd
            if found.public_times is None and f.public_times is not None:
                found.public_times = f.public_times
            if found.placing_times is None and f.placing_times is not None:
                found.placing_times = f.placing_times
            # stop early if all needed filled
            if (not miss["hit"] or found.hit_rate is not None) and (not miss["retail"] or found.retail_hkd is not None) and (not miss["public"] or found.public_times is not None) and (not miss["place"] or found.placing_times is not None):
                break

        row_updates = {}
        if miss["hit"] and found.hit_rate is not None:
            row_updates["中签率"] = fmt_percent(found.hit_rate)
        if miss["retail"] and found.retail_hkd is not None:
            row_updates["散户募资金额"] = fmt_hkd_amount(found.retail_hkd)
        if miss["public"] and found.public_times is not None:
            row_updates["公开发售超购倍数"] = fmt_times(found.public_times)
        if miss["place"] and found.placing_times is not None:
            row_updates["配售超购倍数"] = fmt_times(found.placing_times)

        if row_updates:
            updated_rows += 1
            updated_cells += len(row_updates)
            if not args.dry_run:
                if "中签率" in row_updates:
                    tds[need_cols["中签率"]].string = row_updates["中签率"]
                if "散户募资金额" in row_updates:
                    tds[need_cols["散户募资金额"]].string = row_updates["散户募资金额"]
                if "公开发售超购倍数" in row_updates:
                    tds[need_cols["公开发售超购倍数"]].string = row_updates["公开发售超购倍数"]
                if "配售超购倍数" in row_updates:
                    tds[need_cols["配售超购倍数"]].string = row_updates["配售超购倍数"]

        items.append(
            {
                "code": code5,
                "name": name,
                "missing": miss,
                "updates": row_updates,
                "query": query,
                "used": used,
            }
        )

    report = {
        "attempted_rows": attempted_rows,
        "updated_rows": updated_rows,
        "updated_cells": updated_cells,
        "dry_run": bool(args.dry_run),
        "sleep": args.sleep,
        "max_results": args.max_results,
        "items": items,
    }

    (reports / "web_fill_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.dry_run:
        index_path.write_text(str(soup), encoding="utf-8")

    print(
        f"attempted_rows={attempted_rows} updated_rows={updated_rows} updated_cells={updated_cells} report=reports/web_fill_report.json"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
