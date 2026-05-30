#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p reports

printf '\n==> [1/12] Sync pending IPOs from Futunn (待上市)\n'
npm run sync:pending-ipo

printf '\n==> [2/12] Detect current diffs: Futunn vs site\n'
python3 scripts/compare_futunn_vs_site.py

printf '\n==> [3/13] Compare Futunn finished list and add new listed rows if missing\n'
python3 scripts/add_new_ipo_rows_from_futunn.py

printf '\n==> [4/14] Export Futunn finished-list DOM snapshot\n'
node scripts/export_finished_ipo_dom_playwright.mjs

printf '\n==> [5/14] Refresh existing market fields from Futunn finished DOM snapshot\n'
python3 scripts/refresh_index_market_fields_from_dom_json.py

printf '\n==> [6/14] Normalize index table structure before any fills\n'
python3 scripts/fix_index_table_structure.py

printf '\n==> [7/14] Sync HKEX PDF kit for listed IPO directories\n'
python3 scripts/sync_ipo_pdf_kit.py --sleep 0.5 --summary-json reports/sync_ipo_pdf_kit.json

printf '\n==> [8/14] Fill missing metrics from local/HKEX sources\n'
python3 scripts/fill_missing_metrics.py --max 0

printf '\n==> [9/14] Fill public / international offering amounts from HKEX\n'
python3 scripts/fill_public_intl_amounts_from_hkex.py --apply --report reports/public_intl_amount_fill_report.json

printf '\n==> [10/14] Fill retail amount / hit rate / oversubscription from allotment PDFs\n'
python3 scripts/fill_retail_amount.py --limit 0
python3 scripts/fill_hit_and_placing_from_allotment_pdf.py --apply --report reports/hit_and_placing_fill_report.json
python3 scripts/fill_index_from_allotment_pdf.py --limit 0 --update-limit 0 --report reports/index_fill_report.json

printf '\n==> [11/14] Fill clawback / greenshoe from HKEX PDFs\n'
python3 scripts/fill_clawback_and_greenshoe.py --apply --report reports/clawback_greenshoe_report.json

printf '\n==> [12/14] Repair corrupted stock names from source-of-truth mappings\n'
python3 scripts/repair_index_names_from_sources.py

printf '\n==> [13/14] Refresh index meta summary\n'
python3 scripts/refresh_index_meta.py

printf '\n==> [14/14] Re-check diffs after补全\n'
python3 scripts/compare_futunn_vs_site.py

git status --short || true
