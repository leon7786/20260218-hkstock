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


def pdftotext_first_pages(pdf: Path, pages: int = 80, timeout: int = 180) -> str:
    """Extract PDF text.

    Use -layout to preserve table structure and avoid number concatenation.
    """
    try:
        out = subprocess.check_output(
            [
                "pdftotext",
                "-layout",
                "-f",
                "1",
                "-l",
                str(pages),
                "-enc",
                "UTF-8",
                str(pdf),
                "-",
            ],
            timeout=timeout,
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def parse_times(s: str) -> Optional[float]:
    """Parse oversubscription multiple from a line.

    Supports:
    - Chinese: "5,248.15 倍" / "254.50倍"
    - English: "1,800 times" / "0.15 time"

    Notes:
    - We purposely avoid matching common non-oversub numbers in English tables (e.g. "No. of ...").
      So we only accept times/time/x when it is explicitly present.
    """
    s = (s or "").strip()

    m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:倍|᾵)", s)
    if not m:
        m = re.search(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(?:times|time|x)\b", s, flags=re.I)
    if not m:
        return None

    try:
        v = float(m.group(1).replace(",", ""))
    except Exception:
        return None

    # sanity ranges
    if v <= 0 or v > 100000:
        return None
    # avoid obviously unrelated small counts often present near English headings
    if v < 0.2:
        return None
    return v


def _norm_line(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def extract_section_oversub(text: str, section: str) -> Optional[float]:
    """Extract oversub times from the allotment-results details section.

    HKEX PDFs use multiple wordings for the oversub field, e.g.:
    - 認購水平 / Subscription level
    - 認購額 (this is oversub multiple in many notices)

    We intentionally avoid matching summary lines like "國際發售股份數目 : ...".
    Instead we locate the detailed table headings that appear as standalone lines:
    - HK: 香港公開發售
    - Intl: 國際發售 (or 國際配售)

    Strategy:
    - Find section heading line.
    - Within the section, locate the row label (認購水平/認購額/Subscription level).
    - Prefer the nearest "xx倍" (before the label is common in some layouts),
      otherwise fall back to after.
    """

    # Some PDFs have garbled encoding on the detailed table section.
    # A robust fallback is to strip all whitespace and search in the compact string.
    lines = [ln.strip() for ln in (text or "").splitlines()]
    compact = _norm_line(text)

    # Headings differ between Main Board / GEM notices.
    hk_heads = {
        "香港公開發售",
        "香港公开发售",
        "公開發售",
        "公开发售",
    }
    intl_heads = {
        "國際發售",
        "国际发售",
        "國際配售",
        "国际配售",
        "配售",
        "配售項下",
    }

    # Prefer the heading that appears AFTER the detailed-results heading (配發結果詳情/分配結果詳情)
    detail_heads = {
        "配發結果詳情",
        "配发结果详情",
        "分配結果詳情",
        "分配结果详情",
        "配發結果",
        "分配結果",
        "分配结果",
        "Allotment Results Details",
        "Allocation Results Details",
    }
    detail_pos = None
    for i, ln in enumerate(lines):
        n = _norm_line(ln)
        if n in {_norm_line(x) for x in detail_heads}:
            detail_pos = i
            break
        # allow partial match for English headings spanning multiple tokens
        if "allotmentresultsdetails" in n.lower() or "allocationresultsdetails" in n.lower():
            detail_pos = i
            break

    # Some English notices do not have "Allotment Results Details"; fall back to "SUMMARY".
    if detail_pos is None:
        for i, ln in enumerate(lines):
            if _norm_line(ln).lower() == "summary":
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

    # broader English heading match (line may include bullets/prefix)
    if start is None:
        for i, ln in enumerate(lines):
            n = _norm_line(ln).lower()
            if section == "hk" and "hongkongpublicoffering" in n:
                start = i
                break
            if section == "intl" and "internationaloffering" in n:
                start = i
                break

    # last-resort English headings
    if start is None:
        for i, ln in enumerate(lines):
            if section == "hk" and ln.strip().upper() == "HONG KONG PUBLIC OFFERING":
                start = i
                break
            if section == "intl" and ln.strip().upper() == "INTERNATIONAL OFFERING":
                start = i
                break

    if start is None:
        # Compact fallback (handles broken glyph tables):
        # Try to grab the oversub multiple around the HK/Intl blocks.
        # unit marker
        # NOTE: do NOT use word-boundary; many PDF-extracted glyphs are non-\w and would break \b.
        unit = r"(?:倍|᾵|times|time)"

        if section == "hk":
            # e.g. ...香港公開發售...149.37倍... (some PDFs show garbled unit like "᾵")
            m = re.search(r"香港公開發售.{0,800}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*" + unit, compact, flags=re.I)
            if not m:
                m = re.search(r"公開發售.{0,800}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*" + unit, compact, flags=re.I)
        else:
            # Prefer garbled-table intl marker if present (e.g. '⚳晃...' in some PDFs)
            sub = None
            for marker in ["⚳晃", "國際發售", "国际发售", "國際配售", "国际配售"]:
                pos = compact.find(marker)
                if pos != -1:
                    sub = compact[pos : pos + 2600]
                    break
            if sub is None:
                sub = compact

            # Prefer the oversub number near the intl oversub label (garbled: 娵岤柵)
            # We allow the value to appear immediately after the label.
            m = re.search(r"娵岤柵\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*" + unit, sub, flags=re.I)
            if not m:
                m = re.search(r"娵岤柵.{0,40}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*" + unit, sub, flags=re.I)

            # Strong label hit: accept as-is (can be <1.0 meaning under-subscribed).
            if m:
                try:
                    v0 = float(m.group(1).replace(",", ""))
                except Exception:
                    v0 = None
                if v0 is not None and 0.2 <= v0 <= 100000:
                    return v0
                m = None

            if not m:
                # fallback: choose a unit-bearing number from the intl block.
                # If there is only one and it's >=1, take it.
                ms = list(re.finditer(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*" + unit, sub, flags=re.I))
                if len(ms) == 1:
                    m = ms[0]
                elif len(ms) >= 2:
                    # avoid accidentally taking HK value; take the last
                    m = ms[-1]
                else:
                    m = None

            # last-resort for garbled tables: if we see exactly one plausible unit-bearing number overall,
            # use it as intl too (rare, but better than leaving wrong value).
            if not m:
                all_ms = list(re.finditer(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*" + unit, compact, flags=re.I))
                # filter plausible >=1.0
                cands=[]
                for mm in all_ms:
                    try:
                        vv=float(mm.group(1).replace(",",""))
                    except Exception:
                        continue
                    if vv>=1.0:
                        cands.append(vv)
                if len(set(cands))==1 and cands:
                    # return directly via sentinel match
                    return cands[0]

        if m:
            try:
                v = float(m.group(1).replace(",", ""))
                if 0.2 <= v <= 100000:
                    return v
            except Exception:
                pass
        return None

    # Determine a tighter end boundary: stop at the next section heading if present.
    end = min(len(lines), start + 260)
    head_norm = {_norm_line(x) for x in (hk_heads | intl_heads)}
    for j in range(start + 1, end):
        nj = _norm_line(lines[j])
        if nj in head_norm:
            end = j
            break
        # English headings
        up = (lines[j] or "").strip().upper()
        if up in ("HONG KONG PUBLIC OFFERING", "INTERNATIONAL OFFERING"):
            end = j
            break

    for i in range(start, end):
        if re.search(
            r"認\s*購\s*水\s*平|认购水平|認\s*購\s*額|认购额|認\s*購\s*倍\s*數|认购倍数|Subscription\s*level",
            lines[i],
            flags=re.I,
        ):
            # 1) strongest: value appears on the same line as the label (common for 認購額/認購水平)
            v_same = parse_times(lines[i])
            if v_same is not None:
                return v_same

            # English tables may put the numeric value on the same line as the label,
            # but without an explicit 'times' suffix.
            m_inline = re.search(r"\b([0-9]+\.[0-9]+)\b", lines[i])
            if m_inline:
                try:
                    v = float(m_inline.group(1))
                except Exception:
                    v = None
                if v is not None and 0.2 <= v <= 100000:
                    return v

            before = []
            after = []

            # scan a wider window; English tables often have values a bit further down
            for j in range(max(start, i - 20), i):
                v = parse_times(lines[j])
                if v is not None:
                    before.append((i - j, v))  # smaller distance is better

            for j in range(i + 1, min(end, i + 60)):
                v = parse_times(lines[j])
                if v is not None:
                    after.append((j - i, v))

            before.sort(key=lambda x: x[0])
            after.sort(key=lambda x: x[0])

            # 2) prefer nearest after (safer: avoids bleeding from previous section)
            if after:
                return after[0][1]
            if before:
                return before[0][1]

            # 3) English tables sometimes put a bare decimal number on its own line (no 'times').
            for j in range(i + 1, min(end, i + 60)):
                s = (lines[j] or "").strip()
                if not s or any(x in s for x in ["%", "HK$", "USD", "RMB"]):
                    continue
                m = re.search(r"\b([0-9]+\.[0-9]+)\b", s)
                if not m:
                    continue
                try:
                    v = float(m.group(1))
                except Exception:
                    continue
                if 0.2 <= v <= 100000:
                    return v

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
