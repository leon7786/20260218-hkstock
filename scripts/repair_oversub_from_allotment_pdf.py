#!/usr/bin/env python3
"""Repair oversubscription values in docs/index.html using local 配發結果.pdf.

Why:
- Some oversub values in index.html can be wrong due to pdftotext whitespace removal causing
  adjacent numbers to concatenate (e.g. "277" + "34.33倍" -> "27734.33倍").

Policy:
- PDF is source of truth when the file is verified (audit mismatch_count==0).
- We overwrite existing values ONLY when we can extract a strong table-based value from
  the allotment results details.

Targets:
- 公开发售超购倍数 (Hong Kong Public Offering)
- 配售超购倍数 (International Offering / placing)

Extraction method (table-based, line scan):
- Find section heading (香港公開發售 / 國際發售)
- Find row label "認購水平"
- Take the next line (or next few lines) containing "xx倍" and parse xx

Usage:
  python3 scripts/repair_oversub_from_allotment_pdf.py --apply --report reports/oversub_repair_report.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, List, Tuple

from bs4 import BeautifulSoup


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def pdftotext_first_pages(pdf: Path, pages: int = 25, timeout: int = 180) -> str:
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"],
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_times(s: str) -> Optional[float]:
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", s)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", ""))
    except Exception:
        return None
    if v <= 0 or v > 100000:
        return None
    return v


def _norm_line(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def extract_section_oversub(text: str, section: str) -> Optional[float]:
    """Extract oversub times from the *table* section.

    We intentionally avoid matching summary lines like "國際發售股份數目 : ...".
    Instead we locate the table headings that appear as standalone lines:
    - HK: 香港公開發售
    - Intl: 國際發售 (or 國際配售)

    Strategy:
    - Find section heading line.
    - Within the section, locate the column header block that contains "認購水平".
    - Prefer the closest "xx倍" that appears *before* the header (common layout),
      otherwise fall back to after the header.
    """

    lines = [ln.strip() for ln in (text or "").splitlines()]

    hk_heads = {"香港公開發售", "香港公开发售"}
    intl_heads = {"國際發售", "国际发售", "國際配售", "国际配售"}

    # Prefer the heading that appears AFTER the detailed-results heading (配發結果詳情/分配結果詳情)
    detail_heads = {"配發結果詳情", "配发结果详情", "分配結果詳情", "分配结果详情", "配發結果", "分配結果", "分配结果"}
    detail_pos = None
    for i, ln in enumerate(lines):
        if _norm_line(ln) in {_norm_line(x) for x in detail_heads}:
            detail_pos = i
            break

    start = None
    for i, ln in enumerate(lines):
        n = _norm_line(ln)
        if detail_pos is not None and i < detail_pos:
            continue
        if section == "hk" and n in hk_heads:
            start = i
            break
        if section == "intl" and n in intl_heads:
            start = i
            break

    if start is None:
        # English headings (fallback)
        for i, ln in enumerate(lines):
            n = _norm_line(ln).lower()
            if section == "hk" and n in ("hongkongpublicoffering",):
                start = i
                break
            if section == "intl" and n in ("internationaloffering",):
                start = i
                break

    if start is None:
        return None

    end = min(len(lines), start + 200)

    for i in range(start, end):
        if re.search(r"認\s*購\s*水\s*平|认购水平|Subscription\s*level", lines[i], flags=re.I):
            before = []
            after = []

            for j in range(max(start, i - 12), i):
                v = parse_times(lines[j])
                if v is not None:
                    before.append((i - j, v))  # smaller distance is better

            for j in range(i + 1, min(end, i + 12)):
                v = parse_times(lines[j])
                if v is not None:
                    after.append((j - i, v))

            before.sort(key=lambda x: x[0])
            after.sort(key=lambda x: x[0])

            # Prefer the nearest value *before* the header (common HKEX layout).
            if before:
                return before[0][1]
            if after:
                return after[0][1]
            return None

    return None


def fmt_times(v: float) -> str:
    """Format oversubscription times for display.

    Policy:
    - Keep 1 decimal for large values (readability).
    - For small values (<10), keep up to 2 decimals to avoid losing precision,
      but trim trailing zeros.
    """
    if v < 10:
        s = f"{v:.2f}"
        s = s.rstrip("0").rstrip(".")
        return f"{s}倍"
    return f"{v:.1f}倍"


def parse_times_cell(s: str) -> Optional[float]:
    t = (s or "").strip()
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)倍", t)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception:
        return None


@dataclass
class Item:
    code: str
    name: str
    pdf: str
    public_before: str
    placing_before: str
    public_after: str
    placing_after: str
    public_pdf: Optional[float] = None
    placing_pdf: Optional[float] = None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, default=Path("docs/index.html"))
    ap.add_argument("--docs", type=Path, default=Path("docs"))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", type=Path, default=Path("reports/oversub_repair_report.json"))
    args = ap.parse_args()

    html = args.index.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead th")][:20]
    idx: Dict[str, int] = {h: i for i, h in enumerate(ths)}

    need_cols = ["代码", "股票名称", "公开发售超购倍数", "配售超购倍数"]
    for c in need_cols:
        if c not in idx:
            raise SystemExit(f"missing column: {c}")

    code_i = idx["代码"]
    name_i = idx["股票名称"]
    pub_i = idx["公开发售超购倍数"]
    plc_i = idx["配售超购倍数"]

    attempted = 0
    updated = 0
    items: List[Item] = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) != 20:
            continue

        code = tds[code_i].get_text(strip=True)
        name = tds[name_i].get_text(strip=True)
        pub_before = tds[pub_i].get_text(strip=True)
        plc_before = tds[plc_i].get_text(strip=True)

        # find pdf
        ddir = None
        for p in args.docs.glob(f"{code}*"):
            if p.is_dir():
                ddir = p
                break
        if ddir is None:
            continue
        pdf = ddir / "配發結果.pdf"
        if not pdf.exists():
            continue

        text = pdftotext_first_pages(pdf)
        pub_v = extract_section_oversub(text, "hk")
        plc_v = extract_section_oversub(text, "intl")
        if pub_v is None and plc_v is None:
            continue

        attempted += 1

        pub_after = pub_before
        plc_after = plc_before
        changed = False

        if pub_v is not None:
            f = fmt_times(pub_v)
            if f != pub_before:
                pub_after = f
                changed = True
                if args.apply:
                    tds[pub_i].string = f
                    # keep sorting keys consistent with display
                    tds[pub_i]["data-sort"] = f

        if plc_v is not None:
            f = fmt_times(plc_v)
            if f != plc_before:
                plc_after = f
                changed = True
                if args.apply:
                    tds[plc_i].string = f
                    # keep sorting keys consistent with display
                    tds[plc_i]["data-sort"] = f

        if changed:
            updated += 1

        items.append(
            Item(
                code=code,
                name=name,
                pdf=str(pdf),
                public_before=pub_before,
                placing_before=plc_before,
                public_after=pub_after,
                placing_after=plc_after,
                public_pdf=pub_v,
                placing_pdf=plc_v,
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
