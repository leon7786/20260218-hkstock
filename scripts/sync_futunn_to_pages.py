#!/usr/bin/env python3
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STEPS = [
    ("Sync pending IPOs from Futunn (待上市)", "npm run sync:pending-ipo", False),
    ("Add new listed rows from Futunn if missing", "python3 scripts/add_new_ipo_rows_from_futunn.py", False),
    ("Export Futunn finished-list paginated DOM snapshot", "node scripts/export_finished_ipo_dom_playwright.mjs", False),
    ("Refresh existing market fields from Futunn DOM snapshot", "python3 scripts/refresh_index_market_fields_from_dom_json.py", False),
    ("Normalize index table structure", "python3 scripts/fix_index_table_structure.py", False),
    ("Refresh index meta summary", "python3 scripts/refresh_index_meta.py", False),
]


def run_step(idx: int, total: int, title: str, command: str, allow_fail: bool) -> None:
    print(f"\n==> [{idx}/{total}] {title}")
    print(f"$ {command}")
    started = time.time()
    proc = subprocess.run(command, cwd=ROOT, shell=True)
    elapsed = time.time() - started
    if proc.returncode == 0:
        print(f"[ok] {title} ({elapsed:.1f}s)")
        return
    if allow_fail:
        print(f"[warn] {title} failed with code {proc.returncode}, continuing ({elapsed:.1f}s)")
        return
    print(f"[error] {title} failed with code {proc.returncode} ({elapsed:.1f}s)", file=sys.stderr)
    raise SystemExit(proc.returncode)



def main() -> int:
    os.makedirs(ROOT / 'reports', exist_ok=True)
    total = len(STEPS)
    for i, (title, command, allow_fail) in enumerate(STEPS, start=1):
        run_step(i, total, title, command, allow_fail)
    print("\n==> sync finished")
    status = subprocess.run("git status --short || true", cwd=ROOT, shell=True)
    return status.returncode


if __name__ == '__main__':
    raise SystemExit(main())
