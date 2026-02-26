#!/usr/bin/env python3
"""Quarantine PDFs that match a given MD5 within docs/* stock folders.

Usage:
  python3 scripts/quarantine_md5_group.py --md5 <hash> --filename <name.pdf>

Behavior:
- For any docs/<code name>/<filename> whose MD5 matches, move it into
  docs/<code name>/_suspects/<filename>.<md5>.<timestamp>.pdf
- Leaves the original path missing (so downstream sync scripts can re-fetch or mark missing).

Rationale: user preference is "宁可留空也不要填错".
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path
import re

RE_STOCK_DIR = re.compile(r"^(\d{5})\s+(.+)$")


def md5_file(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, default=Path.cwd())
    ap.add_argument("--md5", required=True)
    ap.add_argument("--filename", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    docs = repo / "docs"
    target_md5 = args.md5.lower()
    filename = args.filename

    ts = time.strftime("%Y%m%d-%H%M%S")
    moved = 0
    scanned = 0

    for d in sorted(docs.iterdir()):
        if not d.is_dir():
            continue
        if not RE_STOCK_DIR.match(d.name):
            continue
        p = d / filename
        if not p.exists():
            continue
        scanned += 1
        try:
            h = md5_file(p)
        except Exception:
            continue
        if h.lower() != target_md5:
            continue

        suspects = d / "_suspects"
        dest = suspects / f"{filename}.{h}.{ts}.pdf"
        if args.dry_run:
            print(f"[DRY] {p} -> {dest}")
        else:
            suspects.mkdir(exist_ok=True)
            p.rename(dest)
            print(f"[MOVED] {p} -> {dest}")
        moved += 1

    print(f"scanned_existing={scanned} moved={moved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
