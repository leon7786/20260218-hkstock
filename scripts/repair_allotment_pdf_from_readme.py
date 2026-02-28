#!/usr/bin/env python3
"""Repair docs/*/配發結果.pdf by re-downloading the HKEX link recorded in README.md.

Why:
Some folders currently have FF305 Next Day Disclosure Return or other non-allotment PDFs
saved as 配發結果.pdf, which breaks index.html filling.

This script:
- reads docs/<code name>/README.md
- extracts the HKEX direct link for `配發結果.pdf`
- downloads to temp
- validates by text markers (must NOT be FF305/Next Day; must contain allotment keywords)
- replaces docs/<dir>/配發結果.pdf (backing up old into _suspects)

It is conservative: if validation fails, it does nothing and prints a warning.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests

RE_STOCK_DIR = re.compile(r"^(\d{5})\s+(.+)$")

BAD_MARKERS = [
    "FF305",
    "Next Day Disclosure Return",
    "THIS CIRCULAR IS IMPORTANT",
]

# keywords that should appear in allotment results / final offer price & allotment announcement
GOOD_KWS = [
    "配發結果",
    "配发结果",
    "分配結果",
    "分配结果",
    "最終發售價",
    "最终发售价",
    "Allotment Results",
    "Basis of Allocation",
    "香港公開發售",
    "Hong Kong Public Offering",
]


def md5_file(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pdftotext_first_pages(pdf: Path, pages: int = 6, timeout: int = 60) -> str:
    try:
        out = subprocess.check_output(
            ["pdftotext", "-f", "1", "-l", str(pages), "-enc", "UTF-8", str(pdf), "-"],
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return out.decode("utf-8", "ignore")
    except Exception:
        return ""


def extract_allotment_url(readme: str) -> Optional[str]:
    # find section for `配發結果.pdf` then the HKEX link line
    # robust enough for current README format
    m = re.search(r"`配發結果\.pdf`[\s\S]{0,400}?HKEX\s*直链:\s*(https?://\S+)", readme)
    if not m:
        return None
    url = m.group(1).strip()
    # strip trailing punctuation
    url = url.rstrip(")；;，,")
    return url


def looks_like_allotment(text: str) -> bool:
    if not text.strip():
        return False
    if any(b in text for b in BAD_MARKERS):
        return False
    # require at least 2 good keywords to reduce false positives
    hit = 0
    tl = text.lower()
    for k in GOOD_KWS:
        if any(ch.isalpha() for ch in k):
            if k.lower() in tl:
                hit += 1
        else:
            if k in text:
                hit += 1
    return hit >= 2


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--codes", type=str, default="", help="comma-separated codes (optional)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    docs = repo / "docs"

    code_filter = None
    if args.codes.strip():
        code_filter = {c.strip().zfill(5) for c in args.codes.split(",") if c.strip()}

    replaced = 0
    skipped = 0
    failed = 0

    for d in sorted(docs.iterdir()):
        if not d.is_dir():
            continue
        m = RE_STOCK_DIR.match(d.name)
        if not m:
            continue
        code = m.group(1)
        if code_filter and code not in code_filter:
            continue

        readme = d / "README.md"
        pdf = d / "配發結果.pdf"
        if not readme.exists() or not pdf.exists():
            continue

        url = extract_allotment_url(readme.read_text(encoding="utf-8", errors="ignore"))
        if not url:
            skipped += 1
            continue

        # check current pdf; if already good, skip
        cur_txt = pdftotext_first_pages(pdf, pages=2)
        if looks_like_allotment(cur_txt):
            skipped += 1
            continue

        try:
            r = requests.get(url, timeout=60)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                failed += 1
                print(f"[FAIL] {code} {d.name}: download status={r.status_code}")
                continue
        except Exception as e:
            failed += 1
            print(f"[FAIL] {code} {d.name}: download error {e}")
            continue

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.write(fd, r.content)
        os.close(fd)
        tmp = Path(tmp_path)
        try:
            # Some allotment announcements only show distinguishing keywords after a few pages.
            txt = pdftotext_first_pages(tmp, pages=6)
            if not looks_like_allotment(txt):
                failed += 1
                print(f"[FAIL] {code} {d.name}: downloaded pdf not recognized as allotment")
                continue

            # backup old
            suspects = d / "_suspects"
            ts = time.strftime("%Y%m%d-%H%M%S")
            bak = suspects / f"配發結果.pdf.bad.{md5_file(pdf)}.{ts}.pdf"

            if args.dry_run:
                print(f"[DRY] {code} {d.name}: replace {pdf} (url={url})")
            else:
                suspects.mkdir(exist_ok=True)
                pdf.rename(bak)
                shutil.move(str(tmp), str(pdf))
                print(f"[OK] {code} {d.name}: replaced 配發結果.pdf (url={url})")
                replaced += 1
                continue

        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    print(f"replaced={replaced} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
