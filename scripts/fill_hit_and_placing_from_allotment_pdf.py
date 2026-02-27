#!/usr/bin/env python3
"""Fill "中签率" and "配售超购倍数" from local 配發結果.pdf.

Policy: "先通过 PDF 补充完整，然后通过联网找对的信息填入".
So this script only uses local PDFs.

Targets:
- 中签率 == 0.0% / 未知 / 待定 / —
- 配售超购倍数 == 0.0倍 / 未知 / 待定 / —

Extraction:
- Use pdftotext up to N pages (default 25) because subscription level info often appears later.
- Strong-context regexes; avoid filling ranges like "15倍至50倍".

Usage:
  python3 scripts/fill_hit_and_placing_from_allotment_pdf.py --pages 25 --apply --report reports/hit_placing_from_pdf.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Tuple, List, Dict

from bs4 import BeautifulSoup


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def is_missing_percent(s: str) -> bool:
    t = (s or "").strip()
    return t in ("", "—", "未知", "待定") or (t.startswith("0.0") and t.endswith("%"))


def is_missing_times(s: str) -> bool:
    t = (s or "").strip()
    return t in ("", "—", "未知", "待定") or (t.startswith("0.0") and t.endswith("倍"))


def pdftotext_pages(pdf: Path, pages: int = 25, timeout: int = 120) -> str:
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"],
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def _extract_one_lot_hit_rate(text: str) -> Optional[float]:
    c = re.sub(r"\s+", "", text or "")

    # Chinese
    for pat in [
        r"一手(?:\([^\)]*\))?中籤率[^0-9]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
        r"一手(?:\([^\)]*\))?中签率[^0-9]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
        r"一手(?:\([^\)]*\))?(?:獲配比率|获配比率)[^0-9]{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)%",
    ]:
        m = re.search(pat, c, flags=re.I)
        if m:
            try:
                v = float(m.group(1).replace(",", ""))
            except Exception:
                continue
            if 0 < v <= 100:
                return v

    # English (rare)
    m = re.search(r"one(?:\s|-)?lot[\s\S]{0,80}?success[\s\S]{0,20}?rate[\s\S]{0,20}?([0-9]+(?:\.[0-9]+)?)%", text or "", flags=re.I)
    if m:
        try:
            v = float(m.group(1))
        except Exception:
            v = None
        if v is not None and 0 < v <= 100:
            return v

    return None


def _extract_placing_oversub_times(text: str) -> Optional[float]:
    c = re.sub(r"\s+", "", text or "")

    # Avoid ranges: 15倍至50倍 / 15倍-50倍
    if re.search(r"[0-9]+(?:\.[0-9]+)?倍(?:至|\-|—|~)[0-9]+(?:\.[0-9]+)?倍", c):
        # don't early return; could still contain a separate exact value later
        pass

    # Strong context: (International Offering/Placing) + (oversub) + x倍
    m = re.search(
        r"(國際發售|国际发售|國際配售|国际配售)[\s\S]{0,260}?(?:錄得|录得|超額認購|超额认购|超購|超购|認購倍數|认购倍数|認購水平|认购水平)[\s\S]{0,120}?([0-9][0-9,]*(?:\.[0-9]+)?)倍",
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

    # Sometimes stated as "International Offer ... times"
    m = re.search(
        r"InternationalOffer[\s\S]{0,260}?(?:Subscriptionlevel|subscribed|times)[\s\S]{0,80}?([0-9]+(?:\.[0-9]+)?)times",
        re.sub(r"\s+", "", text or ""),
        flags=re.I,
    )
    if m:
        try:
            v = float(m.group(1))
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
    pdf: str
    hit_before: str
    placing_before: str
    hit_after: str
    placing_after: str
    hit_src: Optional[str] = None
    placing_src: Optional[str] = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=Path("docs/index.html"))
    ap.add_argument("--docs", type=Path, default=Path("docs"))
    ap.add_argument("--pages", type=int, default=25)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", type=Path, default=Path("reports/hit_placing_from_pdf_report.json"))
    args = ap.parse_args()

    html = args.index.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead th")][:20]
    idx: Dict[str, int] = {h: i for i, h in enumerate(ths)}
    for need in ["代码", "中签率", "配售超购倍数"]:
        if need not in idx:
            raise SystemExit(f"missing column: {need}")

    code_i = idx["代码"]
    # name header is 股票名称 (not 名称)
    name_i = idx.get("股票名称")
    hit_i = idx["中签率"]
    placing_i = idx["配售超购倍数"]

    attempted = 0
    updated = 0
    items: List[Item] = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) != 20:
            continue
        code = tds[code_i].get_text(strip=True)
        name = tds[name_i].get_text(strip=True) if name_i is not None else ""

        hit_before = tds[hit_i].get_text(strip=True)
        placing_before = tds[placing_i].get_text(strip=True)

        need_hit = is_missing_percent(hit_before)
        need_placing = is_missing_times(placing_before)
        if not (need_hit or need_placing):
            continue

        attempted += 1

        # find directory
        ddir = None
        for p in args.docs.glob(f"{code}*"):
            if p.is_dir():
                ddir = p
                break
        if ddir is None:
            items.append(
                Item(
                    code=code,
                    name=name,
                    pdf="",
                    hit_before=hit_before,
                    placing_before=placing_before,
                    hit_after=hit_before,
                    placing_after=placing_before,
                )
            )
            continue

        pdf = ddir / "配發結果.pdf"
        if not pdf.exists():
            items.append(
                Item(
                    code=code,
                    name=name,
                    pdf=str(pdf),
                    hit_before=hit_before,
                    placing_before=placing_before,
                    hit_after=hit_before,
                    placing_after=placing_before,
                )
            )
            continue

        text = pdftotext_pages(pdf, pages=args.pages)
        hit_v = _extract_one_lot_hit_rate(text) if need_hit else None
        placing_v = _extract_placing_oversub_times(text) if need_placing else None

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
                pdf=str(pdf),
                hit_before=hit_before,
                placing_before=placing_before,
                hit_after=hit_after,
                placing_after=placing_after,
                hit_src="配發結果.pdf" if hit_v is not None else None,
                placing_src="配發結果.pdf" if placing_v is not None else None,
            )
        )

    args.report.parent.mkdir(exist_ok=True)
    args.report.write_text(
        json.dumps(
            {
                "attempted": attempted,
                "updated": updated,
                "pages": args.pages,
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
