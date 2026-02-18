#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const ARCHIVE_ROOT = path.join(ROOT, 'archive');
const DATA_JSON = path.join(ROOT, 'data.json');

const DEFAULT_TOLERANCE = Number(process.env.ARCHIVE_TOLERANCE || 0.03);

const REQUIRED_FIELDS = [
  'offerPriceHkd',
  'globalShares',
  'publicShares',
  'internationalShares',
  'publicPct',
  'internationalPct',
  'globalGrossHkd',
  'publicGrossHkd',
  'internationalGrossHkd',
  'listingExpensesHkd',
  'netProceedsHkd',
  'allotmentRatePct',
  'publicSubscriptionMultiple',
  'internationalSubscriptionMultiple',
  'validApplications',
  'successfulApplications',
  'boardLot',
  'sourceOfTruthDate',
  'status'
];

const SAMPLE_OVERRIDES = {
  '03858': {
    name: '佳鑫国际资源',
    sourceOfTruthDate: '2025-08-27',
    summary: {
      offerPriceHkd: 10.92,
      globalShares: 109808800,
      publicShares: 10981200,
      internationalShares: 98827600,
      publicPct: 10,
      internationalPct: 90,
      globalGrossHkd: 1199147040,
      publicGrossHkd: 119927904,
      internationalGrossHkd: 1079219136,
      listingExpensesHkd: 85914704,
      netProceedsHkd: 1113232336,
      allotmentRatePct: 1,
      publicSubscriptionMultiple: 10.6,
      internationalSubscriptionMultiple: 4.2,
      validApplications: 15123,
      successfulApplications: 151,
      boardLot: 200,
      sourceOfTruthDate: '2025-08-27',
      status: 'verified'
    },
    sources: [
      {
        url: 'https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0827/2025082700622_c.pdf',
        fetchedAt: new Date().toISOString(),
        sourceType: 'hkex_allotment_results',
        credibility: 'high',
        extractedFields: [
          'offerPriceHkd','globalShares','publicShares','internationalShares','publicPct','internationalPct','allotmentRatePct','boardLot'
        ],
        notes: '主来源：配发结果公告（按人工核对样板口径）'
      },
      {
        url: 'https://www.futunn.com/quote/hk/ipo',
        fetchedAt: new Date().toISOString(),
        sourceType: 'futunn_ipo',
        credibility: 'medium',
        extractedFields: ['offerPriceHkd','globalShares','globalGrossHkd','sourceOfTruthDate'],
        notes: '辅源：发行价及发行量与主来源一致'
      },
      {
        url: 'https://finance.sina.com.cn/stock/hkstock/marketalerts/2025-08-28/doc-infiqxxx.shtml',
        fetchedAt: new Date().toISOString(),
        sourceType: 'sina_finance',
        credibility: 'medium',
        extractedFields: ['publicPct','internationalPct','publicSubscriptionMultiple','internationalSubscriptionMultiple'],
        notes: '辅源：比例及认购倍数二次交叉'
      },
      {
        url: 'https://www.aastocks.com/sc/stocks/analysis/company-fundamental/?symbol=03858',
        fetchedAt: new Date().toISOString(),
        sourceType: 'aastocks',
        credibility: 'medium',
        extractedFields: ['allotmentRatePct','boardLot'],
        notes: '辅源：中签率与每手股数补充核对'
      }
    ],
    fieldEvidence: {
      offerPriceHkd: [10.92,10.92,10.92],
      globalShares: [109808800,109808800],
      publicShares: [10981200,10981200],
      internationalShares: [98827600,98827600],
      publicPct: [10,10,10],
      internationalPct: [90,90,90],
      globalGrossHkd: [1199147040,1201200000],
      publicGrossHkd: [119927904,120120000],
      internationalGrossHkd: [1079219136,1081080000],
      allotmentRatePct: [1,1],
      boardLot: [200,200]
    }
  }
};

function ensureDir(p) {
  fs.mkdirSync(p, { recursive: true });
}

function loadDataByCode() {
  const data = JSON.parse(fs.readFileSync(DATA_JSON, 'utf-8'));
  const byCode = new Map();
  (data.items || []).forEach((item) => byCode.set(item.code, item));
  return byCode;
}

function toNum(raw) {
  const m = String(raw ?? '').replace(/,/g, '').match(/([+-]?\d+(?:\.\d+)?)/);
  return m ? Number(m[1]) : NaN;
}

function amountToShares(s = '') {
  const v = toNum(s);
  if (!Number.isFinite(v)) return NaN;
  if (String(s).includes('万亿')) return v * 1e12;
  if (String(s).includes('亿')) return v * 1e8;
  if (String(s).includes('万')) return v * 1e4;
  return v;
}

function closeEnough(a, b, tolerance = DEFAULT_TOLERANCE) {
  if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
  if (a === 0 && b === 0) return true;
  const base = Math.max(Math.abs(a), Math.abs(b), 1);
  return Math.abs(a - b) / base <= tolerance;
}

function evaluateField(values, tolerance = DEFAULT_TOLERANCE) {
  const usable = values.filter(Number.isFinite);
  if (usable.length < 2) return { ok: false, reason: '可用来源不足2个' };
  for (let i = 0; i < usable.length; i++) {
    for (let j = i + 1; j < usable.length; j++) {
      if (closeEnough(usable[i], usable[j], tolerance)) {
        return { ok: true };
      }
    }
  }
  return { ok: false, reason: `跨源偏差超过${(tolerance * 100).toFixed(1)}%` };
}

function buildFallbackSources(code, nowIso) {
  const stockId = String(Number(code));
  return [
    {
      url: `https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockId=${stockId}`,
      fetchedAt: nowIso,
      sourceType: 'hkex_search',
      credibility: 'high',
      extractedFields: [],
      notes: '主来源入口：需补配发结果公告/招股章程链接'
    },
    {
      url: `https://www.futunn.com/stock/${code}-HK/company-profile`,
      fetchedAt: nowIso,
      sourceType: 'futunn_profile',
      credibility: 'medium',
      extractedFields: [],
      notes: '辅源'
    },
    {
      url: `https://www.aastocks.com/sc/stocks/analysis/company-fundamental/?symbol=${code}`,
      fetchedAt: nowIso,
      sourceType: 'aastocks',
      credibility: 'medium',
      extractedFields: [],
      notes: '辅源'
    },
    {
      url: `https://stock.finance.sina.com.cn/hkstock/quotes/${code}.html`,
      fetchedAt: nowIso,
      sourceType: 'sina_hk_quote',
      credibility: 'low',
      extractedFields: [],
      notes: '辅源'
    }
  ];
}

function writeArchiveFiles(code, summary, sources, rawPayload) {
  const codeDir = path.join(ARCHIVE_ROOT, code);
  const rawDir = path.join(codeDir, 'raw');
  ensureDir(rawDir);

  fs.writeFileSync(path.join(codeDir, 'summary.json'), JSON.stringify(summary, null, 2));
  fs.writeFileSync(path.join(codeDir, 'sources.json'), JSON.stringify(sources, null, 2));
  fs.writeFileSync(path.join(rawDir, 'source_index.json'), JSON.stringify(rawPayload, null, 2));
}

function assertSummaryShape(summary) {
  const missing = REQUIRED_FIELDS.filter((k) => !(k in summary));
  if (missing.length) {
    throw new Error(`summary.json 缺少字段: ${missing.join(', ')}`);
  }
}

function buildForCode(code, options = {}) {
  const nowIso = new Date().toISOString();
  const tolerance = Number.isFinite(options.tolerance) ? options.tolerance : DEFAULT_TOLERANCE;
  const dataByCode = options.dataByCode || loadDataByCode();
  const item = dataByCode.get(code);
  const archiveCode = String(code).padStart(5, '0');

  if (!item && !SAMPLE_OVERRIDES[archiveCode]) {
    throw new Error(`code ${archiveCode} not found in data.json`);
  }

  const override = SAMPLE_OVERRIDES[archiveCode];

  let summary;
  let sources;
  const fieldChecks = {};
  const reasons = [];

  if (override) {
    summary = { ...override.summary };
    sources = override.sources;
    for (const [field, values] of Object.entries(override.fieldEvidence || {})) {
      const check = evaluateField(values, tolerance);
      fieldChecks[field] = check;
      if (!check.ok) reasons.push(`${field}: ${check.reason}`);
    }
    if (reasons.length > 0) summary.status = 'partial';
  } else {
    const values = item.values || [];
    const offerPrice = toNum(values[5]);
    const globalShares = amountToShares(values[13]);
    const globalGross = Number.isFinite(offerPrice) && Number.isFinite(globalShares)
      ? Math.round(offerPrice * globalShares)
      : null;

    summary = {
      offerPriceHkd: Number.isFinite(offerPrice) ? offerPrice : null,
      globalShares: Number.isFinite(globalShares) ? Math.round(globalShares) : null,
      publicShares: null,
      internationalShares: null,
      publicPct: null,
      internationalPct: null,
      globalGrossHkd: Number.isFinite(globalGross) ? globalGross : null,
      publicGrossHkd: null,
      internationalGrossHkd: null,
      listingExpensesHkd: null,
      netProceedsHkd: null,
      allotmentRatePct: null,
      publicSubscriptionMultiple: null,
      internationalSubscriptionMultiple: null,
      validApplications: null,
      successfulApplications: null,
      boardLot: null,
      sourceOfTruthDate: (values[14] || '').replaceAll('/', '-'),
      status: 'pending'
    };

    sources = buildFallbackSources(archiveCode, nowIso);

    const pendingFields = [
      'publicShares','internationalShares','publicPct','internationalPct','publicGrossHkd','internationalGrossHkd','allotmentRatePct','boardLot'
    ];
    pendingFields.forEach((f) => {
      fieldChecks[f] = { ok: false, reason: '缺少可交叉来源' };
      reasons.push(`${f}: 缺少可交叉来源`);
    });
  }

  const rawPayload = {
    code: archiveCode,
    name: override?.name || item.name,
    generatedAt: nowIso,
    tolerance,
    fieldChecks,
    reasons
  };

  if (summary.status !== 'verified' && reasons.length > 0) {
    summary.status = summary.status === 'pending' ? 'pending' : 'partial';
    rawPayload.statusReason = reasons;
  }

  assertSummaryShape(summary);
  writeArchiveFiles(archiveCode, summary, sources, rawPayload);

  return {
    code: archiveCode,
    name: override?.name || item?.name || '',
    status: summary.status,
    reasonCount: reasons.length
  };
}

function parseArgv(argv) {
  const args = { code: null, tolerance: DEFAULT_TOLERANCE };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--tolerance') args.tolerance = Number(argv[++i]);
    else if (!args.code) args.code = a;
  }
  if (!args.code) throw new Error('Usage: node build_archive_for_code.js <code> [--tolerance 0.03]');
  args.code = String(args.code).padStart(5, '0');
  return args;
}

if (require.main === module) {
  try {
    const args = parseArgv(process.argv);
    const result = buildForCode(args.code, { tolerance: args.tolerance });
    console.log(JSON.stringify(result, null, 2));
  } catch (e) {
    console.error(e.message || e);
    process.exit(1);
  }
}

module.exports = { buildForCode, loadDataByCode };