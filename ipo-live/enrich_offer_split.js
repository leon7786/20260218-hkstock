const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const DATA_PATH = path.join(ROOT, 'data.json');
const OUT_PATH = path.join(ROOT, 'verified_offer_split.json');

const DEFAULT_TOLERANCE = Number(process.env.SPLIT_TOLERANCE || 0.05); // 5%
const FETCH_TIMEOUT_MS = Number(process.env.SPLIT_FETCH_TIMEOUT_MS || 12000);
const LIMIT = Number(process.env.SPLIT_LIMIT || 0); // 0 = all

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function fetchText(url) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(url, {
      signal: ctrl.signal,
      headers: {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
      }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.text();
  } finally {
    clearTimeout(timer);
  }
}

function cleanText(html = '') {
  return String(html)
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function parseNum(raw) {
  if (raw == null) return null;
  const v = Number(String(raw).replace(/,/g, ''));
  return Number.isFinite(v) ? v : null;
}

function toHkdFromLabel(num, unitLabel = '') {
  if (!Number.isFinite(num)) return null;
  if (unitLabel.includes('万亿')) return num * 1e12;
  if (unitLabel.includes('亿')) return num * 1e8;
  if (unitLabel.includes('万')) return num * 1e4;
  return num;
}

function pickMinGap(values = [], tolerance = DEFAULT_TOLERANCE) {
  if (!Array.isArray(values) || values.length < 2) return null;
  let best = null;
  for (let i = 0; i < values.length; i++) {
    for (let j = i + 1; j < values.length; j++) {
      const a = values[i];
      const b = values[j];
      if (!Number.isFinite(a.value) || !Number.isFinite(b.value)) continue;
      const base = Math.max(Math.abs(a.value), Math.abs(b.value), 1e-9);
      const relDiff = Math.abs(a.value - b.value) / base;
      if (relDiff <= tolerance) {
        if (!best || relDiff < best.relDiff) {
          best = { a, b, relDiff, value: (a.value + b.value) / 2 };
        }
      }
    }
  }
  return best;
}

function extractMetrics(source, text) {
  const results = [];
  const push = (field, value, snippet) => {
    if (!Number.isFinite(value)) return;
    results.push({ source, field, value, snippet: String(snippet || '').slice(0, 180) });
  };

  const rePublicPct = [
    /公开发售[^。；\n]{0,80}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%/gi,
    /香港公开发售[^。；\n]{0,80}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%/gi,
  ];
  const reIntlPct = [
    /国际发售[^。；\n]{0,80}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%/gi,
    /配售[^。；\n]{0,80}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%/gi,
  ];
  const reAllot = [
    /(?:中签率|一手中签率)[^。；\n]{0,40}?([0-9]{1,3}(?:\.[0-9]+)?)\s*%/gi,
  ];
  const rePublicAmt = [
    /公开发售[^。；\n]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万亿|亿|万)?\s*港元/gi,
    /香港公开发售[^。；\n]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万亿|亿|万)?\s*港元/gi,
  ];
  const reIntlAmt = [
    /国际发售[^。；\n]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万亿|亿|万)?\s*港元/gi,
    /配售[^。；\n]{0,80}?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万亿|亿|万)?\s*港元/gi,
  ];

  const runPct = (arr, field) => {
    for (const re of arr) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(text)) !== null) {
        const v = parseNum(m[1]);
        if (v == null || v < 0 || v > 100) continue;
        push(field, v, m[0]);
      }
    }
  };

  const runAmt = (arr, field) => {
    for (const re of arr) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(text)) !== null) {
        const n = parseNum(m[1]);
        const hkd = toHkdFromLabel(n, m[2] || '');
        if (!Number.isFinite(hkd) || hkd <= 0) continue;
        push(field, hkd, m[0]);
      }
    }
  };

  runPct(rePublicPct, 'publicPct');
  runPct(reIntlPct, 'internationalPct');
  runPct(reAllot, 'allotmentRatePct');
  runAmt(rePublicAmt, 'publicAmountHkd');
  runAmt(reIntlAmt, 'internationalAmountHkd');

  return results;
}

function dedupeCandidateRows(rows) {
  const seen = new Set();
  return rows.filter(r => {
    const k = `${r.source}|${r.field}|${r.value.toFixed(8)}|${r.snippet}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function buildSources(code) {
  const numCode = String(Number(code));
  return [
    { name: 'sina', url: `https://stock.finance.sina.com.cn/hkstock/quotes/${code}.html` },
    { name: 'aastocks', url: `https://www.aastocks.com/sc/stocks/analysis/company-fundamental/?symbol=${code}` },
    { name: 'futunn', url: `https://www.futunn.com/stock/${code}-HK/company-profile` },
    { name: 'hkex', url: `https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockId=${numCode}` }
  ];
}

async function collectForStock(item) {
  const { code, name } = item;
  const attempts = [];
  const candidates = [];

  const sourceJobs = buildSources(code).map(async (src) => {
    const startedAt = new Date().toISOString();
    try {
      const html = await fetchText(src.url);
      const text = cleanText(html);
      const extracted = extractMetrics(src.name, text);
      return {
        attempt: { source: src.name, url: src.url, ok: true, extracted: extracted.length, startedAt },
        extracted: extracted.map(x => ({ ...x, url: src.url }))
      };
    } catch (e) {
      return {
        attempt: { source: src.name, url: src.url, ok: false, error: e.message, startedAt },
        extracted: []
      };
    }
  });

  const sourceResults = await Promise.all(sourceJobs);
  for (const s of sourceResults) {
    attempts.push(s.attempt);
    candidates.push(...s.extracted);
  }

  const rows = dedupeCandidateRows(candidates);
  const grouped = rows.reduce((acc, r) => {
    acc[r.field] = acc[r.field] || [];
    acc[r.field].push(r);
    return acc;
  }, {});

  const out = {
    code,
    name,
    status: 'pending',
    pendingReasons: [],
    evidence: attempts,
  };

  const fields = ['publicPct', 'internationalPct', 'publicAmountHkd', 'internationalAmountHkd', 'allotmentRatePct'];
  let verifiedFieldCount = 0;

  for (const f of fields) {
    const best = pickMinGap(grouped[f] || [], DEFAULT_TOLERANCE);
    if (best) {
      out[f] = Number(best.value.toFixed(6));
      out.evidence.push({
        field: f,
        matched: true,
        tolerance: DEFAULT_TOLERANCE,
        relDiff: Number(best.relDiff.toFixed(6)),
        pair: [best.a, best.b]
      });
      verifiedFieldCount += 1;
    } else {
      out[f] = null;
      const srcCount = new Set((grouped[f] || []).map(x => x.source)).size;
      if (srcCount < 2) out.pendingReasons.push(`${f}: 可用来源不足2个`);
      else out.pendingReasons.push(`${f}: 多来源差异超出容差${Math.round(DEFAULT_TOLERANCE * 100)}%`);
    }
  }

  if (verifiedFieldCount > 0) {
    out.status = 'partial';
  }
  if (verifiedFieldCount === fields.length) {
    out.status = 'verified';
  }

  if (verifiedFieldCount === 0 && out.pendingReasons.length === 0) {
    out.pendingReasons.push('未抽取到可用字段');
  }

  return out;
}

async function main() {
  if (!fs.existsSync(DATA_PATH)) {
    throw new Error(`data.json not found: ${DATA_PATH}`);
  }

  const data = JSON.parse(fs.readFileSync(DATA_PATH, 'utf-8'));
  const items = Array.isArray(data.items) ? data.items : [];
  const runItems = LIMIT > 0 ? items.slice(0, LIMIT) : items;

  const result = {
    generatedAt: new Date().toISOString(),
    tolerance: DEFAULT_TOLERANCE,
    total: runItems.length,
    stats: {
      verified: 0,
      partial: 0,
      pending: 0
    },
    byCode: {}
  };

  for (let i = 0; i < runItems.length; i++) {
    const it = runItems[i];
    const row = await collectForStock(it);
    result.byCode[it.code] = row;
    result.stats[row.status] += 1;
    console.log(`[${i + 1}/${runItems.length}] ${it.code} ${it.name} -> ${row.status}`);
  }

  fs.writeFileSync(OUT_PATH, JSON.stringify(result, null, 2), 'utf-8');
  console.log(`written: ${OUT_PATH}`);
  console.log(`stats: verified=${result.stats.verified}, partial=${result.stats.partial}, pending=${result.stats.pending}`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
