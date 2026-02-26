#!/usr/bin/env python3
"""Fill "散户募资金额" in docs/index.html.

Policy (per user):
- Prefer extracting from local HKEX PDFs.
- If PDFs cannot yield the value reliably, fallback to *web search*.
- Conservative: only fill when we have high confidence; otherwise leave as '—'.

Definition we use:
- 散户募资金额 ~= 香港公开发售(=Public Offering) 募资额（港元）
- If not explicitly stated as amount, compute as:
    retail_amount_hkd = public_offering_shares * offer_price_hkd

Outputs:
- reports/retail_amount_fill_report.json

Usage:
  python3 scripts/fill_retail_amount.py --limit 30 --dry-run
  python3 scripts/fill_retail_amount.py --limit 400

Notes:
- This is best-effort. Many PDFs are scanned; pdftotext may be weak.
- Web fallback uses DuckDuckGo HTML results (no API key).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus


RE_DIR = re.compile(r"^(\d{5})\s+(.+)$")


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def parse_money_to_hkd(s: str) -> Optional[float]:
    """Parse strings like '4.29亿港元', '7585万港元', '3000.0 万港元', '750万港元'."""
    if not s:
        return None
    t = s.strip().replace(" ", "")
    if t in ("—", "未知", "待定"):
        return None
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
    # Prefer 万/亿
    if hkd >= 1e8:
        v = hkd / 1e8
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{s}亿港元"
    v = hkd / 1e4
    # show 0 decimal if near int else 1
    if abs(v - round(v)) < 0.05:
        return f"{int(round(v))}万港元"
    return f"{v:.1f}万港元"


def pdftotext_first_pages(pdf: Path, pages: int = 12, timeout: int = 60) -> str:
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"],
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?")


def pick_last_number(s: str) -> Optional[float]:
    nums = _NUM_RE.findall(s or "")
    if not nums:
        return None
    try:
        return float(nums[-1].replace(",", ""))
    except Exception:
        return None


def extract_offer_price_hkd(text: str) -> Optional[float]:
    compact = re.sub(r"\s+", "", text)
    # Common patterns
    for pat in [
        r"發售價[:：]?每股發售股份([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"每股發售股份([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"最終發售價[:：]?(?:每股)?(?:H股)?([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"最終發售價[:：]?每股(?:H股)?([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"OfferPrice(?:perShare)?[:：]?HK\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]:
        m = re.search(pat, compact, flags=re.IGNORECASE)
        if m:
            return pick_last_number(m.group(1))
    return None


def extract_public_offering_shares(text: str) -> Optional[int]:
    compact = re.sub(r"\s+", "", text)
    # Look for '香港發售股份數目/香港公开发售股份数目/公開發售股份數目'
    pats = [
        r"香港公開發售[^\d]{0,200}?(?:提呈發售|可供認購|初步提呈發售|項下提呈發售)[^\d]{0,120}?([0-9][0-9,]*)股",
        r"香港公開發售項下[^\d]{0,120}?([0-9][0-9,]*)股",
        r"香港發售股份數目[^\d]{0,80}?([0-9][0-9,]*)股",
        r"香港發售股份數 目[^\d]{0,120}?([0-9][0-9,]*)股",
        r"香港发售股份数目[^\d]{0,80}?([0-9][0-9,]*)股",
        r"公開發售股份數目[^\d]{0,80}?([0-9][0-9,]*)股",
        r"公開發售股份數 目[^\d]{0,120}?([0-9][0-9,]*)股",
        r"HongKongPublicOffering[^\d]{0,120}?([0-9][0-9,]*)shares",
    ]
    for pat in pats:
        m = re.search(pat, compact, flags=re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except Exception:
                continue
    return None


def extract_retail_amount_from_pdf(dir_path: Path) -> Tuple[Optional[float], str, Dict]:
    """Return (amount_hkd, reason, debug)."""
    debug = {}
    for fn in ["配發結果.pdf", "正式通告.pdf", "上市文件.pdf"]:
        pdf = dir_path / fn
        if not pdf.exists():
            continue
        txt = pdftotext_first_pages(pdf, pages=12)
        if not txt.strip():
            continue

        # 1) Explicit amount mention (rare)
        compact = re.sub(r"\s+", "", txt)
        m = re.search(
            r"香港公開發售[\s\S]{0,60}?(?:集資|筹资|籌資|募集|募資)[\s\S]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿|億|万|萬)港元",
            compact,
        )
        if m:
            v = float(m.group(1).replace(",", ""))
            unit = m.group(2)
            amount = v * (1e8 if unit in ("亿", "億") else 1e4)
            debug = {"fn": fn, "method": "explicit", "match": m.group(0)[:120]}
            return amount, "pdf-explicit", debug

        # 2) compute shares * price
        price = extract_offer_price_hkd(txt)
        shares = extract_public_offering_shares(txt)
        debug = {"fn": fn, "price": price, "shares": shares}
        if price is not None and shares is not None and price > 0 and shares > 0:
            return shares * price, "pdf-computed", debug

    return None, "pdf-not-found", debug


@dataclass
class WebHit:
    url: str
    title: str = ""


def ddg_search_urls(query: str, max_results: int = 5, timeout: int = 30) -> List[WebHit]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    hits = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        title = a.get_text(strip=True)
        if not href:
            continue
        hits.append(WebHit(url=href, title=title))
        if len(hits) >= max_results:
            break
    return hits


def extract_amount_from_web_page(url: str, code5: str, name: str, timeout: int = 30) -> Tuple[Optional[float], str]:
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return None, "fetch-fail"
    if r.status_code != 200:
        return None, f"status-{r.status_code}"

    text = r.text
    # quick identity gate
    ident_ok = (code5 in text) or (name and name[:2] in text)
    if not ident_ok:
        # still allow if url contains code
        if code5 not in url:
            return None, "identity-miss"

    compact = re.sub(r"\s+", "", text)
    m = re.search(r"香港公開發售[\s\S]{0,120}?(?:集資|筹资|籌資|募集|募資)[\s\S]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿|億|万|萬)港元", compact)
    if m:
        v = float(m.group(1).replace(",", ""))
        unit = m.group(2)
        amount = v * (1e8 if unit in ("亿", "億") else 1e4)
        return amount, "web-explicit"

    return None, "no-match"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--sleep", type=float, default=0.4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    docs = repo / "docs"
    index = docs / "index.html"
    reports = repo / "reports"
    reports.mkdir(exist_ok=True)

    soup = BeautifulSoup(index.read_text(encoding="utf-8"), "html.parser")
    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead tr th")]
    idx = {h: i for i, h in enumerate(ths)}
    if "散户募资金额" not in idx:
        raise SystemExit("column 散户募资金额 not found")

    ret_i = idx["散户募资金额"]

    updated = 0
    attempted = 0
    items = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) <= ret_i:
            continue
        code5 = tds[1].get_text(strip=True).zfill(5)
        retail = tds[ret_i].get_text(strip=True)
        if retail not in ("—", ""):
            continue
        attempted += 1
        if attempted > args.limit:
            break

        dlist = [p for p in docs.iterdir() if p.is_dir() and p.name.startswith(code5 + " ")]
        if not dlist:
            items.append({"code": code5, "status": "no-dir"})
            continue
        d = dlist[0]
        name = d.name.split(" ", 1)[1]

        amount, why, debug = extract_retail_amount_from_pdf(d)
        src = None

        # web fallback
        if amount is None:
            q = f"{code5} {name} 香港公開發售 集資 港元"
            hits = ddg_search_urls(q, max_results=4)
            time.sleep(args.sleep)
            for h in hits:
                a2, w2 = extract_amount_from_web_page(h.url, code5, name)
                if a2 is not None:
                    amount = a2
                    why = w2
                    src = h.url
                    break
                time.sleep(args.sleep)

        if amount is not None:
            newv = fmt_hkd_amount(amount)
            if not args.dry_run:
                tds[ret_i].string = newv
            updated += 1
            items.append({"code": code5, "dir": d.name, "new": newv, "why": why, "src": src, "debug": debug})
        else:
            items.append({"code": code5, "dir": d.name, "status": "no-fill", "why": why, "src": src, "debug": debug})

    report = {
        "attempted": attempted,
        "updated": updated,
        "dry_run": bool(args.dry_run),
        "items": items,
    }
    (reports / "retail_amount_fill_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.dry_run:
        index.write_text(str(soup), encoding="utf-8")

    print(f"attempted={attempted} updated={updated} report=reports/retail_amount_fill_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
