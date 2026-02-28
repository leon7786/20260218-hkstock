#!/usr/bin/env python3
"""Fill '公开募资' and '国际发售' amounts from local HKEX PDFs.

User request: treat '未知/待定/0.0 港元/—' as missing and overwrite when we can compute reliably.

Definition:
- 公开募资 (HKD) = 香港公开发售最终股份数目 * 最终发售价
- 国际发售 (HKD) = 国际发售最终股份数目 * 最终发售价

Sources (PDF priority): 配發結果.pdf -> 正式通告.pdf -> 上市文件.pdf
Extraction window: pdftotext first 12 pages (per prior constraint).

Output:
- reports/public_intl_amount_fill_report.json

Safety:
- Only fill when both (price, shares) are found and sane.
- Does NOT attempt OCR.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Tuple

from bs4 import BeautifulSoup


def norm_header(h: str) -> str:
    return (h or "").replace("↕", "").strip()


def _parse_amount_to_hkd(s: str) -> Optional[float]:
    t = (s or "").strip().replace(" ", "")
    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿|億|万|萬)港元", t)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = m.group(2)
    return v * (1e8 if unit in ("亿", "億") else 1e4)


def is_missing_amount(s: str) -> bool:
    """Treat placeholders AND obviously invalid values as missing.

    We allow overwriting:
    - placeholders: 未知/待定/—/0.0 港元
    - absurd values caused by bad extraction: < 1e6 HKD or > 1e12 HKD
    """

    t = (s or "").strip()
    if t in ("", "—", "未知", "待定"):
        return True
    if t.startswith("0.0") and "港元" in t:
        return True
    hkd = _parse_amount_to_hkd(t)
    if hkd is not None and (hkd < 1e6 or hkd > 1e12):
        return True
    return False


def pick_last_number(s: str) -> Optional[float]:
    nums = re.findall(r"\d{1,3}(?:,\d{3})*(?:\.\d+)?", s or "")
    if not nums:
        return None
    try:
        return float(nums[-1].replace(",", ""))
    except Exception:
        return None


def pdftotext_first_pages(pdf: Path, pages: int = 12, timeout: int = 90) -> str:
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"],
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def extract_offer_price_hkd(text: str) -> Optional[float]:
    compact = re.sub(r"\s+", "", text)
    for pat in [
        r"最終發售價[:：]?(?:每股)?(?:H股)?([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"最終發售價[:：]?每股(?:H股)?([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"發售價[:：]?每股發售股份([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"每股發售股份([0-9][0-9,]*(?:\.[0-9]+)?)港元",
        r"Offer\s*Price[\s\S]{0,30}?HK\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)",
    ]:
        m = re.search(pat, compact, flags=re.I)
        if m:
            return pick_last_number(m.group(1))
    return None


def extract_final_shares(text: str) -> Tuple[Optional[int], Optional[int]]:
    """Return (hk_public_shares, intl_shares).

    IMPORTANT: pdftotext output often contains tables. We must avoid mis-reading
    "No. of valid applications" / "No. of placees" as shares.

    Strategy:
    - Prefer ALLOTMENT RESULTS DETAILS table:
      - HK: find the line starting with "Final no. of Offer Shares under the Hong Kong Public" and then
            take the first plausible integer from the following few lines.
      - Intl: similarly for "Final no. of Offer Shares under the International".
    - Fallback to compact regexes (Chinese/English) if table parse fails.

    Shares sanity: 1,000 <= shares <= 500,000,000
    """

    def sane_shares(v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        # Offer share counts are typically in millions. Values below 100,000 are almost always
        # application counts / placees / lot sizes accidentally captured.
        if v < 100_000 or v > 500_000_000:
            return None
        return v

    def first_int_in_lines(lines) -> Optional[int]:
        """Pick the first plausible *share count* integer in a small table window.

        Avoid counts like "No. of valid applications" (often < 500k) or "No. of successful applications".
        Heuristic: require at least 7 digits (>= 1,000,000) OR an explicit 'H Shares' indicator in nearby lines.
        """

        joined = " ".join(lines)
        has_h_shares = bool(re.search(r"H\s*Shares", joined, flags=re.I))

        for ln in lines:
            m = re.search(r"\b([0-9][0-9,]{2,})\b", ln)
            if not m:
                continue
            try:
                v = int(m.group(1).replace(",", ""))
            except Exception:
                continue

            # If table doesn't show 'H Shares', be conservative: need >= 1,000,000 to be a share count.
            if not has_h_shares and v < 1_000_000:
                continue

            v = sane_shares(v)
            if v is not None:
                return v
        return None

    lines = [ln.strip() for ln in (text or "").splitlines()]
    lo = "\n".join(lines).lower()

    hk = None
    intl = None

    # 1) Table parse
    # Locate the HK label line index
    for i, ln in enumerate(lines):
        if re.search(r"Final\s+no\.\s+of\s+Offer\s+Shares\s+under\s+the\s+Hong\s+Kong\s+Public", ln, flags=re.I):
            hk = first_int_in_lines(lines[i : i + 10])
            break

    for i, ln in enumerate(lines):
        if re.search(r"Final\s+no\.\s+of\s+Offer\s+Shares\s+under\s+the\s+International", ln, flags=re.I):
            intl = first_int_in_lines(lines[i : i + 12])
            break

    hk = sane_shares(hk)
    intl = sane_shares(intl)
    if hk is not None and intl is not None:
        return hk, intl

    # 2) Fallback parsing for Chinese layouts
    # Prefer line-based parsing: the number is often on the next line, and the same block
    # also contains percent lines (10%/90%) that must be ignored.

    def find_after_label(label_re: str, window: int = 12) -> Optional[int]:
        for i, ln in enumerate(lines):
            if re.search(label_re, ln, flags=re.I):
                v = first_int_in_lines(lines[i : i + window])
                return sane_shares(v)
        return None

    # Accept spaced Chinese words (e.g. 最 終 發 售 股 份 數 目)
    hk_labels = [
        # allow spaces inside 發售
        r"香港公開發\s*售.*最\s*終\s*發\s*售\s*股\s*份\s*數\s*目",
        r"香港公开发\s*售.*最\s*终\s*发\s*售\s*股\s*份\s*数\s*目",
    ]
    intl_labels = [
        r"國際發\s*售.*最\s*終\s*發\s*售\s*股\s*份\s*數\s*目",
        r"国际发\s*售.*最\s*终\s*发\s*售\s*股\s*份\s*数\s*目",
    ]

    if hk is None:
        for lr in hk_labels:
            hk = find_after_label(lr)
            if hk is not None:
                break

    if intl is None:
        for lr in intl_labels:
            intl = find_after_label(lr)
            if intl is not None:
                break

    if hk is not None and intl is not None:
        return hk, intl

    # 3) Last-resort regex on compact text (very conservative)
    compact = re.sub(r"\s+", "", text or "")

    def get_int(pat: str) -> Optional[int]:
        m = re.search(pat, compact, flags=re.I)
        if not m:
            return None
        try:
            return sane_shares(int(m.group(1).replace(",", "")))
        except Exception:
            return None

    if hk is None:
        hk = get_int(r"香港公開發售項下的最終發售股份數目[^0-9]{0,80}?([0-9][0-9,]*)")

    if intl is None:
        intl = get_int(r"國際發售項下的最終發售股份數目[^0-9]{0,80}?([0-9][0-9,]*)")

    return hk, intl


def fmt_hkd_amount(hkd: float) -> str:
    if hkd <= 0:
        return "0.0 港元"
    if hkd >= 1e8:
        v = hkd / 1e8
        return f"{v:.1f}亿港元"
    v = hkd / 1e4
    return f"{v:.1f}万港元"


@dataclass
class Item:
    code: str
    name: str
    price: Optional[float]
    hk_shares: Optional[int]
    intl_shares: Optional[int]
    hk_amount: Optional[float]
    intl_amount: Optional[float]
    src_pdf: str


def extract_from_dir(dir_path: Path) -> Item:
    code = dir_path.name.split()[0]
    name = "".join(dir_path.name.split()[1:])

    price = None
    hk_shares = None
    intl_shares = None
    src = ""

    for fn in ["配發結果.pdf", "正式通告.pdf", "上市文件.pdf"]:
        pdf = dir_path / fn
        if not pdf.exists():
            continue
        text = pdftotext_first_pages(pdf, pages=12)
        if not text.strip():
            continue
        if price is None:
            price = extract_offer_price_hkd(text)
        if hk_shares is None or intl_shares is None:
            hk, intl = extract_final_shares(text)
            hk_shares = hk_shares or hk
            intl_shares = intl_shares or intl
        src = fn
        if price is not None and hk_shares is not None and intl_shares is not None:
            break

    hk_amount = price * hk_shares if price and hk_shares else None
    intl_amount = price * intl_shares if price and intl_shares else None

    return Item(
        code=code,
        name=name,
        price=price,
        hk_shares=hk_shares,
        intl_shares=intl_shares,
        hk_amount=hk_amount,
        intl_amount=intl_amount,
        src_pdf=src,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--limit", type=int, default=99999)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path, default=Path("reports/public_intl_amount_fill_report.json"))
    args = ap.parse_args()

    repo = args.repo.resolve()
    index_path = repo / "docs" / "index.html"
    reports_dir = repo / "reports"
    reports_dir.mkdir(exist_ok=True)

    soup = BeautifulSoup(index_path.read_text(encoding="utf-8"), "html.parser")
    ths = [norm_header(th.get_text(strip=True)) for th in soup.select("table thead tr th")]
    idx = {h: i for i, h in enumerate(ths[:20])}

    for col in ("代码", "股票名称", "公开募资", "国际发售"):
        if col not in idx:
            raise SystemExit(f"missing column: {col}")

    code_i = idx["代码"]
    name_i = idx["股票名称"]
    hk_i = idx["公开募资"]
    intl_i = idx["国际发售"]

    attempted = 0
    updated = 0
    items = []

    for tr in soup.select("table tbody tr"):
        tds = tr.find_all("td")
        if len(tds) != 20:
            continue

        code = tds[code_i].get_text(strip=True).zfill(5)
        name = tds[name_i].get_text(strip=True)

        hk_txt = tds[hk_i].get_text(strip=True)
        intl_txt = tds[intl_i].get_text(strip=True)

        if not (is_missing_amount(hk_txt) or is_missing_amount(intl_txt)):
            continue

        attempted += 1
        if attempted > args.limit:
            break

        # locate dir
        ddir = next((p for p in (repo / "docs").iterdir() if p.is_dir() and p.name.startswith(code)), None)
        if not ddir:
            continue

        item = extract_from_dir(ddir)
        item.name = name
        items.append(asdict(item))

        row_updates = {}
        if is_missing_amount(hk_txt) and item.hk_amount and item.hk_amount > 0:
            row_updates["公开募资"] = fmt_hkd_amount(item.hk_amount)
        if is_missing_amount(intl_txt) and item.intl_amount and item.intl_amount > 0:
            row_updates["国际发售"] = fmt_hkd_amount(item.intl_amount)

        if row_updates and not args.dry_run:
            if "公开募资" in row_updates:
                tds[hk_i].string = row_updates["公开募资"]
            if "国际发售" in row_updates:
                tds[intl_i].string = row_updates["国际发售"]
            updated += 1

    if not args.dry_run:
        index_path.write_text(str(soup), encoding="utf-8")

    args.report.parent.mkdir(exist_ok=True)
    args.report.write_text(
        json.dumps({"attempted": attempted, "updated": updated, "items": items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"attempted={attempted} updated={updated} report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
