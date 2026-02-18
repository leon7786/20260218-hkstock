const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const OUT_DIR = __dirname;
const OUT_JSON = path.join(OUT_DIR, 'data.json');
const OUT_HTML = path.join(OUT_DIR, 'index.html');
const ARCHIVE_DIR = path.join(OUT_DIR, 'archive');
const STOCK_ARCHIVES_DIR = path.join(OUT_DIR, '..', 'stock-archives');

const headers = [
  '上市日期','代码','中签率','股票名称','价格','公开募资','国际发售','首日涨幅','暗盘涨跌额','暗盘涨跌幅','累计涨幅','发行价','涨跌幅','连涨天数','成交量','成交额','换手率','市盈率(静)','总市值','发行量'
];

function isEtfName(name = '') {
  const raw = String(name).trim();
  const n = raw.toUpperCase();

  const keywordHit = [
    'ETF', 'ETP', '杠杆', '反向', '两倍做空', 'QQQ', 'MSCI', 'GLOBALX', 'GX',
    '南方A500', 'A500', 'A泰康', '泰康港元', '泰康美元',
    '易方达', '景顺', '银河博时', '恒生股息', '黄金矿业', '国指兑'
  ].some(k => n.includes(k.toUpperCase()));

  const classShareLike = /-(R|U)$/.test(raw);
  return keywordHit || classShareLike;
}

function loadArchiveSummaryByCode() {
  const out = {};
  if (!fs.existsSync(ARCHIVE_DIR)) return out;
  const dirs = fs.readdirSync(ARCHIVE_DIR, { withFileTypes: true }).filter(d => d.isDirectory());
  for (const d of dirs) {
    const p = path.join(ARCHIVE_DIR, d.name, 'summary.json');
    if (!fs.existsSync(p)) continue;
    try {
      out[d.name] = JSON.parse(fs.readFileSync(p, 'utf-8'));
    } catch (_) {}
  }
  return out;
}

function parseSharesFromText(text, labelRegexList = []) {
  for (const rx of labelRegexList) {
    const m = text.match(rx);
    if (!m) continue;
    const n = Number(String(m[1]).replace(/,/g, ''));
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function parseOfferPriceFromText(text) {
  const rules = [
    /最终发售价[^\n]{0,80}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /Final Offer Price[^\n]{0,120}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i
  ];
  for (const rx of rules) {
    const m = text.match(rx);
    if (!m) continue;
    const n = Number(m[1]);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function loadDisclosureByCode() {
  const out = {};

  const hkexJson = path.join(OUT_DIR, 'hkex-disclosure.json');
  if (fs.existsSync(hkexJson)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(hkexJson, 'utf-8'));
      const byCode = parsed?.byCode || {};
      for (const [code, v] of Object.entries(byCode)) {
        if (v && v.status === 'ok' && Number.isFinite(Number(v.offerPriceHkd)) && Number.isFinite(Number(v.publicShares))) {
          out[String(code).padStart(5, '0')] = {
            offerPriceHkd: Number(v.offerPriceHkd),
            publicShares: Number(v.publicShares),
            internationalShares: Number.isFinite(Number(v.internationalShares)) ? Number(v.internationalShares) : null,
            globalShares: Number.isFinite(Number(v.globalShares)) ? Number(v.globalShares) : null,
            publicGrossHkd: Number.isFinite(Number(v.publicGrossHkd)) ? Number(v.publicGrossHkd) : null,
            internationalGrossHkd: Number.isFinite(Number(v.internationalGrossHkd)) ? Number(v.internationalGrossHkd) : null,
            sourceType: 'hkex_auto_pdf_parse'
          };
        }
      }
    } catch (_) {}
  }

  if (!fs.existsSync(STOCK_ARCHIVES_DIR)) return out;

  const files = fs.readdirSync(STOCK_ARCHIVES_DIR).filter(f => f.endsWith('.txt'));
  for (const file of files) {
    const codeMatch = file.match(/^(\d{5})\s/);
    if (!codeMatch) continue;
    const code = codeMatch[1];
    const fullPath = path.join(STOCK_ARCHIVES_DIR, file);

    let text = '';
    try { text = fs.readFileSync(fullPath, 'utf-8'); } catch (_) { continue; }

    const publicShares = parseSharesFromText(text, [
      /香港公开发售[^\n]*?\|[^\n]*?([\d,]+)\s*H股/,
      /HK Public Offering[^\n]*?([\d,]+)\s*H股/i
    ]);
    const internationalShares = parseSharesFromText(text, [
      /国际发售[^\n]*?\|[^\n]*?([\d,]+)\s*H股/,
      /International Offering[^\n]*?([\d,]+)\s*H股/i
    ]);
    const globalShares = parseSharesFromText(text, [
      /全球发售股份[^\n]*?\|[^\n]*?([\d,]+)\s*H股/,
      /Offer Shares[^\n]*?\|[^\n]*?([\d,]+)\s*H股/i,
      /全球发售股份数[^\n]*?([\d,]+)\s*H股/
    ]);
    const offerPriceHkd = parseOfferPriceFromText(text);

    if (Number.isFinite(publicShares) && Number.isFinite(offerPriceHkd)) {
      const totalShares = Number.isFinite(globalShares)
        ? globalShares
        : (Number.isFinite(internationalShares) ? (publicShares + internationalShares) : null);

      out[code] = {
        offerPriceHkd,
        publicShares,
        internationalShares,
        globalShares: Number.isFinite(totalShares) ? totalShares : null,
        publicGrossHkd: Math.round(publicShares * offerPriceHkd),
        // 按用户口径："国际发售金额" 列展示总募资金额（总股份 × 发售价）
        internationalGrossHkd: Number.isFinite(totalShares) ? Math.round(totalShares * offerPriceHkd) : null,
        sourceType: 'hkex_disclosureeasylike_archive'
      };
    }
  }

  return out;
}

async function scrape() {
  const browser = await chromium.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-gpu']
  });

  const page = await browser.newPage();
  page.setDefaultTimeout(45000);
  await page.goto('https://www.futunn.com/quote/hk/ipo', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(5000);

  const all = [];

  for (let p = 1; p <= 5; p++) {
    if (p > 1) {
      const pager = page.locator('.base-pagination .item', { hasText: String(p) }).first();
      await pager.click();
      await page.waitForTimeout(2500);
    }

    const rows = await page.$$eval('a.list-item', (els) => {
      return els.map((el) => {
        const code = el.querySelector('.code')?.textContent?.trim() || '';
        const name = el.querySelector('.name')?.textContent?.trim() || '';
        const values = Array.from(el.querySelectorAll('.value')).map(v => v.textContent.trim());
        return { code, name, values };
      });
    });

    for (const r of rows) all.push({ page: p, ...r });
  }

  await browser.close();

  const hasDarkPoolData = (r) => {
    const v = r?.values || [];
    const amt = String(v[2] ?? '').trim();
    const pct = String(v[3] ?? '').trim();
    const bad = new Set(['', '-', '--', '---', '----', '0', '0.00%', '0.000', '0.000%']);
    return !(bad.has(amt) || bad.has(pct));
  };

  const filtered = all.filter(r => r.code && r.name && !isEtfName(r.name) && hasDarkPoolData(r));

  const payload = {
    source: 'https://www.futunn.com/quote/hk/ipo',
    scrapedAt: new Date().toISOString(),
    pages: 5,
    rawCount: all.length,
    filteredCount: filtered.length,
    headers,
    items: filtered
  };

  fs.writeFileSync(OUT_JSON, JSON.stringify(payload, null, 2), 'utf-8');
  return payload;
}

function buildHtml(data, archiveSummaryByCode = {}, disclosureByCode = {}) {
  const fmtHkd = (n) => {
    if (!Number.isFinite(n)) return '-';
    if (n >= 1e8) return `${(n/1e8).toFixed(1)} 亿港元`;
    if (n >= 1e4) return `${(n/1e4).toFixed(1)} 万港元`;
    return `${n.toFixed(1)} 港元`;
  };
  const fmtPct = (n) => Number.isFinite(n) ? `${n.toFixed(1)}%` : '待定';

  const formatOneDecimal = (raw='') => {
    const s = String(raw ?? '').trim();
    if (!s || s === '-' || /^\d{4}\/\d{2}\/\d{2}$/.test(s)) return s || '-';
    const m = s.match(/^([+-]?\d+(?:\.\d+)?)(.*)$/);
    if (!m) return s;
    const n = Number(m[1]);
    if (!Number.isFinite(n)) return s;
    const suffix = m[2] || '';
    return `${n.toFixed(1)}${suffix}`;
  };

  const numSortVal = (raw='') => {
    const s = String(raw ?? '').replace(/,/g,'').trim();
    if (!s || s === '-') return Number.NEGATIVE_INFINITY;
    if (/^\d{4}\/\d{2}\/\d{2}$/.test(s)) return new Date(s.split('/').join('-')).getTime();
    const m = s.match(/([+-]?\d+(?:\.\d+)?)/);
    if (!m) return Number.NEGATIVE_INFINITY;
    let n = Number(m[1]);
    if (!Number.isFinite(n)) return Number.NEGATIVE_INFINITY;
    if (s.includes('亿')) n *= 1e8;
    else if (s.includes('万')) n *= 1e4;
    return n;
  };

  const rowsHtml = data.items.map(r => {
    const v = r.values || [];
    const code = String(r.code).padStart(5, '0');
    const summary = archiveSummaryByCode[code] || null;
    const disclosure = disclosureByCode[code] || null;

    const strictUsable = summary && summary.status === 'verified';

    const summaryPublicAmount = strictUsable && Number.isFinite(Number(summary.publicGrossHkd)) ? Number(summary.publicGrossHkd) : null;
    const summaryInternationalAmount = strictUsable && Number.isFinite(Number(summary.internationalGrossHkd)) ? Number(summary.internationalGrossHkd) : null;
    const summaryPublicPct = strictUsable && Number.isFinite(Number(summary.publicPct)) ? Number(summary.publicPct) : null;
    const summaryInternationalPct = strictUsable && Number.isFinite(Number(summary.internationalPct)) ? Number(summary.internationalPct) : null;

    const disclosurePublicAmount = disclosure && Number.isFinite(Number(disclosure.publicGrossHkd)) ? Number(disclosure.publicGrossHkd) : null;
    const disclosureInternationalAmount = disclosure && Number.isFinite(Number(disclosure.internationalGrossHkd)) ? Number(disclosure.internationalGrossHkd) : null;

    const publicAmount = Number.isFinite(summaryPublicAmount) ? summaryPublicAmount : disclosurePublicAmount;
    const internationalAmount = Number.isFinite(summaryInternationalAmount) ? summaryInternationalAmount : disclosureInternationalAmount;

    const publicPct = Number.isFinite(summaryPublicPct) ? summaryPublicPct : null;
    const internationalPct = Number.isFinite(summaryInternationalPct) ? summaryInternationalPct : null;
    const allotmentRatePct = strictUsable && Number.isFinite(Number(summary.allotmentRatePct)) ? Number(summary.allotmentRatePct) : null;

    const publicText = Number.isFinite(publicAmount)
      ? (Number.isFinite(publicPct) ? `${fmtPct(publicPct)}：${fmtHkd(publicAmount)}` : fmtHkd(publicAmount))
      : '待定';
    const internationalText = Number.isFinite(internationalAmount)
      ? (Number.isFinite(internationalPct) ? `${fmtPct(internationalPct)}：${fmtHkd(internationalAmount)}` : fmtHkd(internationalAmount))
      : '待定';

    const splitTitle = strictUsable
      ? `建档口径（${summary.sourceOfTruthDate || '未标注日期'}）`
      : (disclosure ? '披露易口径（公开=公开发售股数×发售价；国际列按你的规则显示总股份×发售价）' : '待建档或披露易资料未补齐');

    const tds = [
      `<td data-col="上市日期" data-sort="${(v[14] ?? '-').replace(/"/g,'&quot;')}">${v[14] ?? '-'}</td>`,
      `<td class="code" data-sort="${r.code}">${r.code}</td>`,
      `<td data-col="中签率" data-sort="${Number.isFinite(allotmentRatePct) ? allotmentRatePct : -1}">${Number.isFinite(allotmentRatePct) ? fmtPct(allotmentRatePct) : '待定'}</td>`,
      `<td class="name" data-sort="${r.name}">${r.name}</td>`,
      `<td data-col="价格" data-sort="${(v[0] ?? '-').replace(/"/g,'&quot;')}">${formatOneDecimal(v[0] ?? '-')}</td>`,
      `<td data-col="公开募资" data-sort="${publicAmount ?? -1}" title="${splitTitle}">${publicText}</td>`,
      `<td data-col="国际发售" data-sort="${internationalAmount ?? -1}" title="${splitTitle}">${internationalText}</td>`,
      `<td data-col="首日涨幅" data-sort="${(v[1] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[1])}">${formatOneDecimal(v[1] ?? '-')}</td>`,
      `<td data-col="暗盘涨跌额" data-sort="${(v[2] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[2])}">${formatOneDecimal(v[2] ?? '-')}</td>`,
      `<td data-col="暗盘涨跌幅" data-sort="${(v[3] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[3])}">${formatOneDecimal(v[3] ?? '-')}</td>`,
      `<td data-col="累计涨幅" data-sort="${(v[4] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[4])}">${formatOneDecimal(v[4] ?? '-')}</td>`,
      `<td data-col="发行价" data-sort="${(v[5] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[5])}">${formatOneDecimal(v[5] ?? '-')}</td>`,
      `<td data-col="涨跌幅" data-sort="${(v[6] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[6])}">${formatOneDecimal(v[6] ?? '-')}</td>`,
      `<td data-col="连涨天数" data-sort="${(v[7] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[7])}">${formatOneDecimal(v[7] ?? '-')}</td>`,
      `<td data-col="成交量" data-sort="${(v[8] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[8])}">${formatOneDecimal(v[8] ?? '-')}</td>`,
      `<td data-col="成交额" data-sort="${(v[9] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[9])}">${formatOneDecimal(v[9] ?? '-')}</td>`,
      `<td data-col="换手率" data-sort="${(v[10] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[10])}">${formatOneDecimal(v[10] ?? '-')}</td>`,
      `<td data-col="市盈率(静)" data-sort="${(v[11] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[11])}">${formatOneDecimal(v[11] ?? '-')}</td>`,
      `<td data-col="总市值" data-sort="${(v[12] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[12])}">${formatOneDecimal(v[12] ?? '-')}</td>`,
      `<td data-col="发行量" data-sort="${(v[13] ?? '-').replace(/"/g,'&quot;')}" data-sort-num="${numSortVal(v[13])}">${formatOneDecimal(v[13] ?? '-')}</td>`
    ].join('');
    return `<tr>${tds}</tr>`;
  }).join('\n');

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Futunn IPO（已排除ETF）</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:16px}
.wrap{max-width:1600px;margin:0 auto}
h1{margin:0 0 8px;font-size:24px}
.meta{color:#94a3b8;margin-bottom:12px;font-size:13px}
.table{overflow:auto;border:1px solid #334155;border-radius:10px}
table{border-collapse:collapse;min-width:1450px;width:100%;background:#0b1222}
th,td{border-bottom:1px solid #1e293b;padding:8px 10px;text-align:left;font-size:13px;white-space:nowrap}
th{position:sticky;top:0;background:#111b33;z-index:1;cursor:pointer;user-select:none}
th:hover{background:#172445}
th .arrow{opacity:.55;margin-left:4px;font-size:11px}
th.sorted .arrow{opacity:1;color:#93c5fd}
tr:hover{background:#111827}
.code{font-weight:700;color:#93c5fd}.name{font-weight:600}
</style>
</head>
<body>
<div class="wrap">
  <h1>Futunn 港股IPO（已排除ETF）</h1>
  <div class="meta">来源：<a href="${data.source}" target="_blank" style="color:#93c5fd">${data.source}</a> ｜ 抓取时间：${new Date(data.scrapedAt).toLocaleString('zh-CN', {hour12:false})} ｜ 抓取页数：${data.pages} ｜ 原始条目：${data.rawCount} ｜ 过滤后：${data.filteredCount} ｜ 建档目录：archive/&lt;code&gt;/summary.json</div>
  <div class="meta" style="margin-bottom:12px">
    <button id="btn-sort-cum" style="background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:4px 8px;cursor:pointer">累计涨幅↓</button>
  </div>
  <div class="table">
    <table>
      <thead>
        <tr>${headers.map((h,idx)=>`<th data-index="${idx}">${h}<span class="arrow">↕</span></th>`).join('')}</tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  </div>
</div>
<script>
(function(){
  const table = document.querySelector('table');
  const tbody = table.querySelector('tbody');
  const headers = Array.from(table.querySelectorAll('thead th'));
  const parseVal = (txt) => {
    const s = (txt || '').trim();
    if (!s || s === '-') return Number.NEGATIVE_INFINITY;
    if (/^\d{4}[\/]\d{2}[\/]\d{2}$/.test(s)) return new Date(s.split('/').join('-')).getTime();
    const m = s.replace(/,/g, '').match(/([+-]?\d+(?:\.\d+)?)/);
    if (m) {
      const num = Number(m[1]);
      if (!Number.isFinite(num)) return Number.NEGATIVE_INFINITY;
      if (s.includes('%')) return num;
      if (s.includes('亿')) return num * 1e8;
      if (s.includes('万')) return num * 1e4;
      return num;
    }
    return s;
  };
  const columnState = {};
  const sortBy = (idx, dir='desc') => {
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a,b)=>{
      const aCell = a.children[idx];
      const bCell = b.children[idx];
      const at = aCell?.getAttribute('data-sort-num') || aCell?.getAttribute('data-sort') || aCell?.innerText || '';
      const bt = bCell?.getAttribute('data-sort-num') || bCell?.getAttribute('data-sort') || bCell?.innerText || '';
      const av = parseVal(at), bv = parseVal(bt);

      const an = typeof av === 'number' ? av : Number.NaN;
      const bn = typeof bv === 'number' ? bv : Number.NaN;
      const aNum = Number.isFinite(an) || an === Number.NEGATIVE_INFINITY;
      const bNum = Number.isFinite(bn) || bn === Number.NEGATIVE_INFINITY;

      if (aNum && bNum) return dir==='desc' ? (bn-an) : (an-bn);
      if (aNum && !bNum) return dir==='desc' ? -1 : 1;
      if (!aNum && bNum) return dir==='desc' ? 1 : -1;

      return dir==='desc'
        ? String(bv).localeCompare(String(av), 'zh-Hans-CN')
        : String(av).localeCompare(String(bv), 'zh-Hans-CN');
    });
    rows.forEach(r=>tbody.appendChild(r));
    headers.forEach((h,i)=>{
      h.classList.toggle('sorted', i===idx);
      const arr = h.querySelector('.arrow');
      arr.textContent = i===idx ? (dir==='desc' ? '↓' : '↑') : '↕';
    });
    columnState[idx] = dir;
  };
  headers.forEach(h=>h.addEventListener('click',()=>{
    const idx = Number(h.dataset.index);
    const last = columnState[idx];
    const dir = !last ? 'desc' : (last === 'desc' ? 'asc' : 'desc');
    sortBy(idx, dir);
  }));

  const cumBtn = document.getElementById('btn-sort-cum');
  if (cumBtn) {
    cumBtn.addEventListener('click',()=>{
      const cumIdx = headers.findIndex(h => h.textContent.includes('累计涨幅'));
      sortBy(cumIdx >= 0 ? cumIdx : 0, 'desc');
    });
  }

  const dateIdx = headers.findIndex(h => h.textContent.includes('上市日期'));
  sortBy(dateIdx >= 0 ? dateIdx : 0, 'desc');
})();
</script>
</body>
</html>`;
}

(async () => {
  try {
    const archiveSummaryByCode = loadArchiveSummaryByCode();
    const disclosureByCode = loadDisclosureByCode();
    const data = await scrape();
    fs.writeFileSync(OUT_HTML, buildHtml(data, archiveSummaryByCode, disclosureByCode), 'utf-8');
    console.log(`done: raw=${data.rawCount}, filtered=${data.filteredCount}, archived=${Object.keys(archiveSummaryByCode).length}, disclosure=${Object.keys(disclosureByCode).length}`);
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();