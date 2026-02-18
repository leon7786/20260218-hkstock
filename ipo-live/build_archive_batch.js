#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { buildForCode, loadDataByCode } = require('./build_archive_for_code');

const DATA_JSON = path.join(__dirname, 'data.json');

function parseArgs(argv) {
  const args = { limit: null, tolerance: undefined };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--limit') args.limit = Number(argv[++i]);
    else if (a === '--tolerance') args.tolerance = Number(argv[++i]);
  }
  return args;
}

function loadCodesFromData() {
  const data = JSON.parse(fs.readFileSync(DATA_JSON, 'utf-8'));
  const seen = new Set();
  const codes = [];
  for (const item of data.items || []) {
    const code = String(item.code || '').padStart(5, '0');
    if (code && !seen.has(code)) {
      seen.add(code);
      codes.push(code);
    }
  }
  return codes;
}

function runBatch({ limit, tolerance }) {
  const codes = loadCodesFromData();
  const selected = Number.isFinite(limit) && limit > 0 ? codes.slice(0, limit) : codes;
  const dataByCode = loadDataByCode();

  const results = [];
  const stats = { verified: 0, partial: 0, pending: 0 };

  for (const code of selected) {
    const r = buildForCode(code, { tolerance, dataByCode });
    results.push(r);
    stats[r.status] = (stats[r.status] || 0) + 1;
  }

  return {
    generatedAt: new Date().toISOString(),
    total: selected.length,
    stats,
    results
  };
}

if (require.main === module) {
  try {
    const args = parseArgs(process.argv);
    const out = runBatch(args);
    console.log(JSON.stringify(out, null, 2));
  } catch (e) {
    console.error(e.message || e);
    process.exit(1);
  }
}

module.exports = { runBatch };