#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill missing IPO metrics (hit rate / oversubscription) into docs/index.html.

Strategy:
1) Parse docs/index.html, find rows where:
   - 中签率 (td index 2) is '—'
   - 配售超购倍数 (td index 4) is '—'
   - 公开发售超购倍数 (td index 5) is '—'
2) For each code, try extract from local docs/<code name>/配發結果.pdf via pdftotext.
3) If extraction fails (PDF not an allotment results announcement), attempt re-download
   via Playwright HKEX title search (tools/hkex_titlesearch_download.js), then retry.
4) Update values with 2 decimals.

Batch mode: commit+push after every N UPDATED stocks (default 10).

Usage:
  python3 scripts/fill_missing_metrics.py --batch 10

Notes:
- This script edits docs/index.html only.
- It will overwrite docs/<code name>/配發結果.pdf if re-downloaded.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs" / "index.html"
DOCS = ROOT / "docs"


@dataclass
class Extracted:
    hit_rate: Optional[float] = None  # %
    public_oversub: Optional[float] = None  # times
    placing_oversub: Optional[float] = None  # times


def run(cmd: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def pdftotext(pdf: Path) -> str:
    cp = run(["pdftotext", str(pdf), "-"])
    if cp.returncode != 0:
        return ""
    return cp.stdout


def parse_num(s: str) -> Optional[float]:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def slice_between(text: str, start_pat: re.Pattern, end_pats: list[re.Pattern]) -> Optional[str]:
    m = start_pat.search(text)
    if not m:
        return None
    start = m.start()
    end = len(text)
    for ep in end_pats:
        m2 = ep.search(text, m.end())
        if m2:
            end = min(end, m2.start())
    return text[start:end]


def extract_hit_rate(text: str) -> Optional[float]:
    # 1) explicit one-lot success rate
    for pat in [
        r"一手(?:中[籤签]率|中[籤签]率|配發比率|分配比率)[^\d%]{0,60}([0-9]+(?:\.[0-9]+)?)\s*%",
    ]:
        m = re.search(pat, text)
        if m:
            v = parse_num(m.group(1))
            if v is not None:
                return v

    # 2) from group A allocation table: "X名中的Y名獲得Z股"
    # Focus within 甲組 section if present.
    sec = slice_between(
        text,
        re.compile(r"甲組"),
        [re.compile(r"乙組"), re.compile(r"國際"), re.compile(r"国际"), re.compile(r"International", re.I)],
    )
    blob = sec or text

    # First match is usually the smallest application tier.
    m = re.search(r"([0-9][0-9,]*)\s*名中的\s*([0-9][0-9,]*)\s*名獲得\s*([0-9][0-9,]*)\s*股", blob)
    if m:
        total = parse_num(m.group(1))
        success = parse_num(m.group(2))
        if total and success is not None and total > 0:
            return success / total * 100.0

    # 3) fallback: "概約百分比" first percent (less ideal, but better than empty)
    m = re.search(r"獲配發股份佔所申請[\s\S]{0,200}?概約百分比[\s\S]{0,400}?\b([0-9]+(?:\.[0-9]+)?)\s*%", text)
    if m:
        v = parse_num(m.group(1))
        if v is not None:
            return v
    return None


def extract_oversub(text: str) -> tuple[Optional[float], Optional[float]]:
    # Public offering section
    hk_sec = (
        slice_between(
            text,
            re.compile(r"香港公開發售"),
            [re.compile(r"國際發售"), re.compile(r"国际发售"), re.compile(r"International\s*Offering", re.I)],
        )
        or slice_between(
            text,
            re.compile(r"Hong\s*Kong\s*Public\s*Offering", re.I),
            [re.compile(r"International\s*Offering", re.I), re.compile(r"International\s*Placing", re.I)],
        )
        or text
    )

    intl_sec = (
        slice_between(text, re.compile(r"國際發售"), [re.compile(r"回補"), re.compile(r"超額配股"), re.compile(r"over\-?allot", re.I)])
        or slice_between(text, re.compile(r"International\s*Offering", re.I), [])
    )

    def find_times(blob: str) -> Optional[float]:
        # Chinese preferred
        for pat in [
            r"認購水平[\s\S]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍",
            r"(?:超額認購|超额认购|超購|超购)[\s\S]{0,80}?(?:約|约)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍",
        ]:
            m = re.search(pat, blob)
            if m:
                v = parse_num(m.group(1))
                if v is not None:
                    return v
        # English
        m = re.search(
            r"over\-?subscribed[\s\S]{0,120}?(?:approximately\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times",
            blob,
            flags=re.I,
        )
        if m:
            v = parse_num(m.group(1))
            if v is not None:
                return v
        return None

    public = find_times(hk_sec)
    placing = find_times(intl_sec) if intl_sec else None
    return public, placing


def looks_like_allotment(text: str) -> bool:
    keys = [
        "認購水平",
        "超購",
        "獲配發股份佔",
        "概約百分比",
        "香港公開發售",
        "Hong Kong Public Offering",
        "over-subscribed",
    ]
    low = text.lower()
    return any((k.lower() in low if k.isascii() else k in text) for k in keys)


def find_dir_by_code(code: str) -> Optional[Path]:
    ms = sorted([p for p in DOCS.iterdir() if p.is_dir() and p.name.startswith(code + " ")])
    return ms[0] if ms else None


def fmt_percent(v: float) -> str:
    return f"{v:.2f}%"


def fmt_times(v: float) -> str:
    return f"{v:.2f}倍"


def redownload_hkex(code: str, name: str) -> bool:
    # Calls Playwright downloader (may download multiple PDFs); we only need 配發結果.pdf
    cp = run(["node", "tools/hkex_titlesearch_download.js", code, name], timeout=300)
    return cp.returncode == 0


def git_commit_push(msg: str) -> None:
    run(["git", "add", "docs/index.html", "scripts/fill_missing_metrics.py", "tools/hkex_titlesearch_download.js", ".gitignore"], timeout=120)
    cp = run(["git", "commit", "-m", msg], timeout=120)
    if cp.returncode != 0:
        # nothing to commit
        return
    run(["git", "push", "origin", "master"], timeout=300)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=10, help="每更新多少只股票就 commit+push 一次")
    ap.add_argument("--max", type=int, default=0, help="最多更新多少只（0=不限）")
    ap.add_argument("--no-download", action="store_true", help="不联网重下 PDF，只用本地")
    args = ap.parse_args()

    soup = BeautifulSoup(INDEX.read_text(encoding="utf-8"), "html.parser")
    rows = soup.select("table tbody tr")

    updated_total = 0
    updated_batch = 0
    batch_codes: list[str] = []

    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        code = tds[1].get_text(strip=True).zfill(5)
        td_hit, td_place, td_public = tds[2], tds[4], tds[5]

        def is_missing(td) -> bool:
            return td.get_text(strip=True) == "—"

        if not (is_missing(td_hit) or is_missing(td_public) or is_missing(td_place)):
            continue

        d = find_dir_by_code(code)
        if not d:
            continue
        name = d.name.split(" ", 1)[1] if " " in d.name else d.name
        pdf = d / "配發結果.pdf"
        if not pdf.exists():
            continue

        text = pdftotext(pdf)
        if not looks_like_allotment(text) and (not args.no_download):
            # try download and retry
            redownload_hkex(code, name)
            text = pdftotext(pdf)

        ex = Extracted()
        if looks_like_allotment(text):
            ex.hit_rate = extract_hit_rate(text)
            ex.public_oversub, ex.placing_oversub = extract_oversub(text)

        row_changed = False
        if is_missing(td_hit) and ex.hit_rate is not None:
            v = fmt_percent(ex.hit_rate)
            td_hit["data-sort"] = v
            td_hit.string = v
            row_changed = True

        if is_missing(td_public) and ex.public_oversub is not None:
            v = fmt_times(ex.public_oversub)
            td_public["data-sort"] = v
            td_public.string = v
            row_changed = True

        if is_missing(td_place) and ex.placing_oversub is not None:
            v = fmt_times(ex.placing_oversub)
            td_place["data-sort"] = v
            td_place.string = v
            row_changed = True

        if row_changed:
            updated_total += 1
            updated_batch += 1
            batch_codes.append(code)

            if updated_batch >= args.batch:
                INDEX.write_text(str(soup), encoding="utf-8")
                git_commit_push(f"chore(index): fill missing IPO metrics (batch {updated_total-updated_batch+1}-{updated_total}) codes {','.join(batch_codes)}")
                updated_batch = 0
                batch_codes = []

            if args.max and updated_total >= args.max:
                break

    # flush remainder
    if updated_batch > 0:
        INDEX.write_text(str(soup), encoding="utf-8")
        git_commit_push(f"chore(index): fill missing IPO metrics (batch tail) codes {','.join(batch_codes)}")

    print(f"updated_total={updated_total}")


if __name__ == "__main__":
    main()
