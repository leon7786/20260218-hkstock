#!/usr/bin/env python3
"""Audit PDFs under docs/* folders.

Outputs:
- reports/pdf_audit_duplicates.json
- reports/pdf_audit_mismatch.json
- reports/pdf_audit_summary.md

Checks:
1) MD5 duplicates: any PDF files with identical hash across different stock folders.
2) Mismatch: PDF text does not appear to match the folder stock code (best-effort).

Notes:
- Many HKEX PDFs are scanned; pdftotext may return empty => status=unknown.
- We treat '配發結果.pdf' (allotment results) as strict: must contain the stock code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

RE_STOCK_DIR = re.compile(r"^(\d{5})\s+(.+)$")
RE_CODE_5 = re.compile(r"\b(\d{5})\b")

CANON = [
    "上市文件.pdf",
    "正式通告.pdf",
    "配發結果.pdf",
    "綠鞋悉行.pdf",
    "穩價期終.pdf",
]


def md5_file(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def pdftotext_first_pages(p: Path, pages: int = 8, timeout: int = 60) -> str:
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(p), "-"],
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def has_code(text: str, code5: str) -> bool:
    """Best-effort stock code match (kept consistent with sync_ipo_pdf_kit.py)."""

    code5 = str(code5).zfill(5)
    code_no0 = code5.lstrip("0") or code5
    variants = [code5, code_no0]
    if len(code_no0) <= 4:
        variants.append(code_no0.zfill(4))

    if re.search(rf"\b{re.escape(code5)}\b", text):
        return True

    compact = re.sub(r"\s+", "", text)
    for v in variants:
        if v == code5 and v in compact:
            return True
        if re.search(rf"(?<!\d){re.escape(v)}(?!\d)", compact):
            return True
        if re.search(rf"(?:^|\D){re.escape(v)}(?:$|\D)", compact):
            return True

    return False


def simplify_name(name: str) -> str:
    n = name.strip()
    n = re.sub(r"[-－](B|H|W)$", "", n, flags=re.I)
    n = re.sub(r"\s+", "", n)
    return n


def _is_mostly_ascii(s: str) -> bool:
    if not s:
        return False
    ascii_cnt = sum(1 for ch in s if ord(ch) < 128)
    return ascii_cnt / max(1, len(s)) >= 0.9


def has_name(text: str, name: str) -> bool:
    if not name:
        return False
    s = simplify_name(name)
    if not s:
        return False
    t = re.sub(r"\s+", "", text)
    if s in t:
        return True

    if _is_mostly_ascii(s):
        # avoid weak 2~3 letter false positives
        if len(s) >= 4 and s[:4] in t:
            return True
        if len(s) >= 6 and s[:6] in t:
            return True
        return False

    # chinese-ish fallback
    if len(s) >= 2 and s[:2] in t:
        return True
    if len(s) >= 3 and s[:3] in t:
        return True
    return False


@dataclass
class PdfRecord:
    code5: str
    stock_name: str
    relpath: str
    filename: str
    size: int
    md5: str


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    docs = repo / "docs"
    reports = repo / "reports"
    reports.mkdir(exist_ok=True)

    pdfs: List[PdfRecord] = []
    md5_map: Dict[str, List[PdfRecord]] = {}

    # 1) Walk and hash
    for d in sorted(docs.iterdir()):
        if not d.is_dir():
            continue
        m = RE_STOCK_DIR.match(d.name)
        if not m:
            continue
        code5, stock_name = m.group(1), m.group(2).strip()
        for p in sorted(d.glob("*.pdf")):
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            h = md5_file(p)
            rec = PdfRecord(
                code5=code5,
                stock_name=stock_name,
                relpath=str(p.relative_to(repo)),
                filename=p.name,
                size=st.st_size,
                md5=h,
            )
            pdfs.append(rec)
            md5_map.setdefault(h, []).append(rec)

    duplicates = []
    for h, items in md5_map.items():
        if len(items) <= 1:
            continue
        # group by stock code
        codes = sorted({it.code5 for it in items})
        if len(codes) <= 1:
            continue
        duplicates.append(
            {
                "md5": h,
                "count": len(items),
                "codes": codes,
                "files": [
                    {
                        "code": it.code5,
                        "name": it.stock_name,
                        "path": it.relpath,
                        "filename": it.filename,
                        "size": it.size,
                    }
                    for it in items
                ],
            }
        )

    duplicates.sort(key=lambda x: (-x["count"], x["md5"]))

    # 2) Mismatch check (best-effort)
    mismatches = []
    unknown = 0

    # cache pdftotext results per file to avoid reruns
    text_cache: Dict[str, str] = {}

    for rec in pdfs:
        p = repo / rec.relpath
        # Only check canonical set (others might be extra)
        if rec.filename not in CANON:
            continue

        key = rec.relpath
        if key not in text_cache:
            text_cache[key] = pdftotext_first_pages(p, pages=8)
        text = text_cache[key]

        if not text.strip():
            unknown += 1
            continue

        code_ok = has_code(text, rec.code5)
        name_ok = has_name(text, rec.stock_name)

        strict = rec.filename == "配發結果.pdf"

        # collect other codes in doc (to spot obvious mismap)
        other_codes = sorted({c for c in RE_CODE_5.findall(text) if c != rec.code5})
        if strict:
            # For allotment results, many PDFs omit the stock code; require code OR (company name).
            if not (code_ok or name_ok):
                mismatches.append(
                    {
                        "code": rec.code5,
                        "name": rec.stock_name,
                        "file": rec.filename,
                        "path": rec.relpath,
                        "reason": "allotment_results_code_and_name_miss",
                        "other_codes_sample": other_codes[:10],
                    }
                )
        else:
            # Heuristic: if doc contains some other code(s) but not ours AND not our name
            if (not code_ok) and (not name_ok) and other_codes:
                mismatches.append(
                    {
                        "code": rec.code5,
                        "name": rec.stock_name,
                        "file": rec.filename,
                        "path": rec.relpath,
                        "reason": "code_and_name_miss_but_other_code_present",
                        "other_codes_sample": other_codes[:10],
                    }
                )

    # Write reports
    (reports / "pdf_audit_duplicates.json").write_text(
        json.dumps(
            {
                "total_pdfs": len(pdfs),
                "duplicate_groups": len(duplicates),
                "duplicates": duplicates,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    (reports / "pdf_audit_mismatch.json").write_text(
        json.dumps(
            {
                "checked_pdfs": len([p for p in pdfs if p.filename in CANON]),
                "unknown_text_pdfs": unknown,
                "mismatch_count": len(mismatches),
                "mismatches": mismatches,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # Summary markdown
    lines = [
        "# PDF 审计摘要",
        "",
        f"- 总 PDF 数量: {len(pdfs)}",
        f"- 跨股票目录 MD5 完全相同的重复组数: {len(duplicates)}",
        f"- Mismatch（疑似对不上股票代码/名称）条目数: {len(mismatches)}",
        f"- pdftotext 无文本/空文本（无法判断）数量: {unknown}",
        "",
        "## Top 重复组（MD5 相同）",
    ]
    for g in duplicates[:10]:
        lines.append(f"- md5={g['md5']} count={g['count']} codes={','.join(g['codes'][:10])}{'…' if len(g['codes'])>10 else ''}")

    lines += [
        "",
        "## Top 疑似错档（仅展示前 30）",
    ]
    for m in mismatches[:30]:
        lines.append(f"- {m['code']} {m['name']} | {m['file']} | {m['reason']} | other_codes={','.join(m.get('other_codes_sample') or [])}")

    (reports / "pdf_audit_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("Wrote:")
    print("-", reports / "pdf_audit_duplicates.json")
    print("-", reports / "pdf_audit_mismatch.json")
    print("-", reports / "pdf_audit_summary.md")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
