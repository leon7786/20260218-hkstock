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
    # 实务：很多「配發結果」并不会写“一手中签率”字样，而是在甲组表格里用：
    #   「獲配發股份佔所申請總數的概約百分比」列出每个申请档位的百分比。
    # 我们要的是“最小申請档位（通常=1手/最少申请股数）对应的第一个百分比”。

    # a) 先尝试显式表述
    pats = [
        r"一手(?:中[籤签]率|獲配發比率|配發比率|分配比率|中[签籤]率)?[^\d%]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%",
        r"甲組[^\n]{0,120}?(?:第一|首)[^\n]{0,40}?(?:概約|概略|中[籤签]率|獲配發比率)?[^\d%]{0,40}([0-9]+(?:\.[0-9]+)?)\s*%",
    ]
    for pat in pats:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            v = parse_num(m.group(1))
            if v is not None:
                out.hit_rate = v
                break

    # b) 回退：从甲组“概约百分比”列抓第一条百分比
    if out.hit_rate is None:
        m = re.search(r"獲配發股份佔所申請[\s\S]{0,200}?概約百分比[\s\S]{0,400}?\b([0-9]+(?:\.[0-9]+)?)\s*%", text)
        if m:
            v = parse_num(m.group(1))
            if v is not None:
                out.hit_rate = v

    # 2) 超购倍数/认购倍数
    # 中文常见：
    # - 「香港公開發售超額認購約xxx倍」/「公開發售超購xxx倍」
    # - 「香港公開發售認購水平xxx倍」
    # 英文常见：
    # - "Hong Kong Public Offering was over-subscribed by approximately xxx times"

    # a) 中文：公开发售超购/超额认购
    if out.public_oversub is None:
        m = re.search(r"(?:香港)?公開發售[\s\S]{0,200}?(?:超額認購|超额认购|超購|超购)[\s\S]{0,80}?(?:約|约)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text)
        if m:
            out.public_oversub = parse_num(m.group(1))

    # b) 中文：认购水平
    if out.public_oversub is None:
        pub_m = re.search(r"香港公開發售[\s\S]{0,800}?認購水平[\s\S]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text)
        if pub_m:
            out.public_oversub = parse_num(pub_m.group(1))

    # c) 英文兜底：over-subscribed / times
    if out.public_oversub is None:
        m = re.search(
            r"Hong\s*Kong\s*Public\s*Offering[\s\S]{0,400}?over\-?subscribed[\s\S]{0,120}?(?:approximately\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times",
            text,
            flags=re.IGNORECASE,
        )
        if m:
            out.public_oversub = parse_num(m.group(1))
        else:
            m = re.search(
                r"Hong\s*Kong\s*Public\s*Offering[\s\S]{0,200}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times",
                text,
                flags=re.IGNORECASE,
            )
            if m:
                out.public_oversub = parse_num(m.group(1))

    # d) 配售/国际配售（若文本存在）
    if out.placing_oversub is None:
        m = re.search(r"(?:國際發售|国际发售|國際配售|国际配售|International\s*Offering)[\s\S]{0,220}?(?:超額認購|超额认购|超購|超购)[\s\S]{0,80}?(?:約|约)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text, flags=re.IGNORECASE)
        if m:
            out.placing_oversub = parse_num(m.group(1))
        else:
            m = re.search(r"International\s*Offering[\s\S]{0,300}?over\-?subscribed[\s\S]{0,120}?(?:approximately\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*times", text, flags=re.IGNORECASE)
            if m:
                out.placing_oversub = parse_num(m.group(1))

    # e) 最后兜底：若文档里存在多个「認購水平xxx倍」，取第一个当公开、第二个当配售
    levels = [parse_num(x) for x in re.findall(r"認購水平\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*倍", text)]
    levels = [x for x in levels if x is not None]
    if out.public_oversub is None and levels:
        out.public_oversub = levels[0]
    if out.placing_oversub is None and len(levels) >= 2:
        out.placing_oversub = levels[1]

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
    ap.add_argument("--limit", type=int, default=0, help="本次最多扫描多少只缺失股票（0=不限）")
    ap.add_argument("--update-limit", type=int, default=0, help="本次最多实际更新多少只（0=不限，用于每10只一批）")
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

        # scan limit (how many missing rows we examine)
        if args.limit and scanned >= args.limit:
            continue
        scanned += 1

        # update limit (how many rows we actually modify)
        if args.update_limit and touched >= args.update_limit:
            continue

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
