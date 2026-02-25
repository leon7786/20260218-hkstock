#!/usr/bin/env python3
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
    hit_rate: Optional[float] = None
    public_oversub: Optional[float] = None
    placing_oversub: Optional[float] = None


def to_text(pdf: Path) -> str:
    cp = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True)
    if cp.returncode != 0:
        return ""
    return cp.stdout


def parse_num(s: str) -> Optional[float]:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None


def extract_from_text(text: str) -> Extracted:
    out = Extracted()

    # 1) 一手中签率（优先）
    pats = [
        r"一手(?:中[籤签]率|獲配發比率|配發比率|分配比率|中[签籤]率)?[^\d%]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%",
        r"甲組[^\n]{0,120}?(?:第一|首)[^\n]{0,40}?(?:概約|概略|中[籤签]率|獲配發比率)?[^\d%]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%",
        r"甲組[^\n]{0,120}?([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    for pat in pats:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            v = parse_num(m.group(1))
            if v is not None:
                out.hit_rate = v
                break

    # 2) 认购水平（第一个通常是公开发售，第二个是国际配售）
    levels = [parse_num(x) for x in re.findall(r"認購水平\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text)]
    levels = [x for x in levels if x is not None]

    pub_m = re.search(r"香港公開發售[\s\S]{0,420}?認購水平\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text)
    if pub_m:
        out.public_oversub = parse_num(pub_m.group(1))
    elif levels:
        out.public_oversub = levels[0]

    plc_m = re.search(r"國際發售[\s\S]{0,420}?認購水平\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text)
    if plc_m:
        out.placing_oversub = parse_num(plc_m.group(1))
    elif len(levels) >= 2:
        out.placing_oversub = levels[1]

    # 3) 英文补充（如有）
    if out.public_oversub is None:
        m = re.search(r"Hong\s*Kong\s*Public\s*Offering[\s\S]{0,200}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times", text, flags=re.IGNORECASE)
        if m:
            out.public_oversub = parse_num(m.group(1))

    if out.placing_oversub is None:
        m = re.search(r"International\s*Offering[\s\S]{0,220}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times", text, flags=re.IGNORECASE)
        if m:
            out.placing_oversub = parse_num(m.group(1))

    return out


def fmt_percent(v: float) -> str:
    return f"{v:.2f}%"


def fmt_times(v: float) -> str:
    return f"{v:.2f}倍"


def has_missing(td) -> bool:
    return td.get_text(strip=True) == "—"


def find_dir_by_code(code: str) -> Optional[Path]:
    ms = sorted([p for p in DOCS.iterdir() if p.is_dir() and p.name.startswith(code + " ")])
    return ms[0] if ms else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="本次最多处理多少只（0=不限）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / "fill_index_from_allotment_pdf_last.txt")
    args = ap.parse_args()

    soup = BeautifulSoup(INDEX.read_text(encoding="utf-8"), "html.parser")
    rows = soup.select("table tbody tr")

    scanned = 0
    touched = 0
    processed_codes: list[str] = []
    missing_codes: list[str] = []
    logs: list[str] = []

    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        code = tds[1].get_text(strip=True)
        td_hit, td_place, td_public = tds[2], tds[4], tds[5]

        if not (has_missing(td_hit) or has_missing(td_place) or has_missing(td_public)):
            continue

        missing_codes.append(code)
        if args.limit and scanned >= args.limit:
            continue

        scanned += 1
        d = find_dir_by_code(code)
        if not d:
            logs.append(f"{code}: 未找到目录")
            continue
        pdf = d / "配發結果.pdf"
        if not pdf.exists():
            logs.append(f"{code}: 缺少配發結果.pdf")
            continue

        txt = to_text(pdf)
        if not txt.strip():
            logs.append(f"{code}: pdftotext 失败或空文本")
            continue

        ex = extract_from_text(txt)
        row_changed = False

        if has_missing(td_hit) and ex.hit_rate is not None:
            v = fmt_percent(ex.hit_rate)
            td_hit["data-sort"] = v
            td_hit.string = v
            row_changed = True

        if has_missing(td_public) and ex.public_oversub is not None:
            v = fmt_times(ex.public_oversub)
            td_public["data-sort"] = v
            td_public.string = v
            row_changed = True

        if has_missing(td_place) and ex.placing_oversub is not None:
            v = fmt_times(ex.placing_oversub)
            td_place["data-sort"] = v
            td_place.string = v
            row_changed = True

        if row_changed:
            touched += 1
            processed_codes.append(code)
            logs.append(
                f"{code}: 命中 hit={ex.hit_rate} public={ex.public_oversub} placing={ex.placing_oversub}"
            )
        else:
            logs.append(f"{code}: 未提取到可用字段")

    if touched and not args.dry_run:
        INDEX.write_text(str(soup), encoding="utf-8")

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        "\n".join(
            [
                f"missing_total={len(missing_codes)}",
                f"attempted={scanned}",
                f"updated={touched}",
                f"updated_codes={','.join(processed_codes)}",
                "---",
                *logs,
            ]
        ),
        encoding="utf-8",
    )

    print(f"missing_total={len(missing_codes)} attempted={scanned} updated={touched}")
    if processed_codes:
        print("updated_codes=" + ",".join(processed_codes))
    print(f"report={args.report}")


if __name__ == "__main__":
    main()
