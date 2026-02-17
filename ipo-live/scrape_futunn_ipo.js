const fs = require('fs');
const path = require('path');
const { chromium } = require('../node_modules/playwright-core');

const OUT_DIR = __dirname;
const OUT_JSON = path.join(OUT_DIR, 'data.json');
const OUT_HTML = path.join(OUT_DIR, 'index.html');

const headers = [
  '代码','股票名称','价格','公开募资金额(核查)','首日涨幅','暗盘涨跌额','暗盘涨跌幅','累计涨幅','发行价','涨跌幅','连涨天数','成交量','成交额','换手率','市盈率(静)','总市值','发行量','上市日期'
];

// 手工核查值（港元），优先于任何估算
const verifiedPublicOfferByCode = {
  '03858': 120000000, // 佳鑫国际资源：公开募资约1.20亿
  '02513': 870000000  // 智谱：公开募资约8.70亿
};

function isEtfName(name = '') {
  const raw = String(name).trim();
  const n = raw.toUpperCase();

  const keywordHit = [
    // ETF / 指数 / 杠反 / 份额类
    'ETF', 'ETP', '杠杆', '反向', '两倍做空', 'QQQ', 'MSCI', 'GLOBALX', 'GX',
    // 常见基金/产品名称关键字
    '南方A500', 'A500', 'A泰康', '泰康港元', '泰康美元',
    '易方达', '景顺', '银河博时', '恒生股息', '黄金矿业', '国指兑'
  ].some(k => n.includes(k.toUpperCase()));

  const classShareLike = /-(R|U)$/.test(raw); // 常见ETF份额后缀

  return keywordHit || classShareLike;
}

async function scrape() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: '/usr/bin/google-chrome',
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

    for (const r of rows) {
      all.push({ page: p, ...r });
    }
  }

  await browser.close();

  const hasDarkPoolData = (r) => {
    const v = r?.values || [];
    const amt = String(v[2] ?? '').trim();   // 暗盘涨跌额
    const pct = String(v[3] ?? '').trim();   // 暗盘涨跌幅
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

function buildHtml(data) {
  const toNum = (s='') => {
    const m = String(s).replace(/,/g,'').match(/([+-]?\d+(?:\.\d+)?)/);
    return m ? Number(m[1]) : NaN;
  };
  const amountToShares = (s='') => {
    const v = toNum(s);
    if (!Number.isFinite(v)) return NaN;
    if (String(s).includes('万亿')) return v * 1e12;
    if (String(s).includes('亿')) return v * 1e8;
    if (String(s).includes('万')) return v * 1e4;
    return v;
  };
  const fmtHkd = (n) => {
    if (!Number.isFinite(n)) return '-';
    if (n >= 1e8) return `约${(n/1e8).toFixed(2)}亿`;
    if (n >= 1e4) return `约${(n/1e4).toFixed(2)}万`;
    return `约${n.toFixed(0)}`;
  };

  const rowsHtml = data.items.map(r => {
    const v = r.values || [];
    const issuePrice = toNum(v[5]);      // 发行价
    const issueVolume = amountToShares(v[13]); // 发行量
    const estFund = (Number.isFinite(issuePrice) && Number.isFinite(issueVolume)) ? issuePrice * issueVolume : NaN;
    const verifiedPublicOffer = verifiedPublicOfferByCode[r.code];

    const tds = [
      `<td class="code" data-sort="${r.code}">${r.code}</td>`,
      `<td class="name" data-sort="${r.name}">${r.name}</td>`,
      `<td data-col="价格" data-sort="${(v[0] ?? '-').replace(/"/g,'&quot;')}">${v[0] ?? '-'}</td>`,
      `<td data-col="公开募资金额(核查)" data-sort="${Number.isFinite(verifiedPublicOffer) ? verifiedPublicOffer : -1}">${Number.isFinite(verifiedPublicOffer) ? fmtHkd(verifiedPublicOffer) : '待核'}</td>`,
      `<td data-col="首日涨幅" data-sort="${(v[1] ?? '-').replace(/"/g,'&quot;')}">${v[1] ?? '-'}</td>`,
      `<td data-col="暗盘涨跌额" data-sort="${(v[2] ?? '-').replace(/"/g,'&quot;')}">${v[2] ?? '-'}</td>`,
      `<td data-col="暗盘涨跌幅" data-sort="${(v[3] ?? '-').replace(/"/g,'&quot;')}">${v[3] ?? '-'}</td>`,
      `<td data-col="累计涨幅" data-sort="${(v[4] ?? '-').replace(/"/g,'&quot;')}">${v[4] ?? '-'}</td>`,
      `<td data-col="发行价" data-sort="${(v[5] ?? '-').replace(/"/g,'&quot;')}">${v[5] ?? '-'}</td>`,
      `<td data-col="涨跌幅" data-sort="${(v[6] ?? '-').replace(/"/g,'&quot;')}">${v[6] ?? '-'}</td>`,
      `<td data-col="连涨天数" data-sort="${(v[7] ?? '-').replace(/"/g,'&quot;')}">${v[7] ?? '-'}</td>`,
      `<td data-col="成交量" data-sort="${(v[8] ?? '-').replace(/"/g,'&quot;')}">${v[8] ?? '-'}</td>`,
      `<td data-col="成交额" data-sort="${(v[9] ?? '-').replace(/"/g,'&quot;')}">${v[9] ?? '-'}</td>`,
      `<td data-col="换手率" data-sort="${(v[10] ?? '-').replace(/"/g,'&quot;')}">${v[10] ?? '-'}</td>`,
      `<td data-col="市盈率(静)" data-sort="${(v[11] ?? '-').replace(/"/g,'&quot;')}">${v[11] ?? '-'}</td>`,
      `<td data-col="总市值" data-sort="${(v[12] ?? '-').replace(/"/g,'&quot;')}">${v[12] ?? '-'}</td>`,
      `<td data-col="发行量" data-sort="${(v[13] ?? '-').replace(/"/g,'&quot;')}">${v[13] ?? '-'}</td>`,
      `<td data-col="上市日期" data-sort="${(v[14] ?? '-').replace(/"/g,'&quot;')}">${v[14] ?? '-'}</td>`
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
  <div class="meta">来源：<a href="${data.source}" target="_blank" style="color:#93c5fd">${data.source}</a> ｜ 抓取时间：${new Date(data.scrapedAt).toLocaleString('zh-CN', {hour12:false})} ｜ 抓取页数：${data.pages} ｜ 原始条目：${data.rawCount} ｜ 过滤后：${data.filteredCount}</div>
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
    if (!s || s === '-') return -Infinity;
    if (/^\\d{4}[\\/]\\d{2}[\\/]\\d{2}$/.test(s)) return new Date(s.split('/').join('-')).getTime();

    let m = s.match(/([+-]?\\d+(?:\\.\\d+)?)/);
    if (m) {
      let num = parseFloat(m[1]);
      if (s.includes('%')) return num;
      if (s.includes('亿')) return num * 1e8;
      if (s.includes('万')) return num * 1e4;
      return num;
    }
    return s;
  };

  let current = { idx: -1, dir: 'desc' };
  const columnState = {}; // 每列单独记录上次方向

  const sortBy = (idx, dir='desc') => {
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((a,b)=>{
      const at = a.children[idx]?.getAttribute('data-sort') || a.children[idx]?.innerText || '';
      const bt = b.children[idx]?.getAttribute('data-sort') || b.children[idx]?.innerText || '';
      const av = parseVal(at), bv = parseVal(bt);
      if (typeof av === 'number' && typeof bv === 'number') return dir==='desc' ? (bv-av) : (av-bv);
      return dir==='desc' ? String(bv).localeCompare(String(av), 'zh-Hans-CN') : String(av).localeCompare(String(bv), 'zh-Hans-CN');
    });
    rows.forEach(r=>tbody.appendChild(r));

    headers.forEach((h,i)=>{
      h.classList.toggle('sorted', i===idx);
      const arr = h.querySelector('.arrow');
      arr.textContent = i===idx ? (dir==='desc' ? '↓' : '↑') : '↕';
    });
    current = { idx, dir };
    columnState[idx] = dir;
  };

  headers.forEach(h=>{
    h.addEventListener('click',()=>{
      const idx = Number(h.dataset.index);
      // 规则：每列首次点击=降序；同列再次点击=升降切换
      const last = columnState[idx];
      const dir = !last ? 'desc' : (last === 'desc' ? 'asc' : 'desc');
      sortBy(idx, dir);
    });
  });

  // 默认按“上市日期”降序，接近Futunn观感
  const dateIdx = headers.findIndex(h => h.textContent.includes('上市日期'));
  sortBy(dateIdx >= 0 ? dateIdx : 0, 'desc');
})();
</script>
</body>
</html>`;
}

(async () => {
  try {
    const data = await scrape();
    fs.writeFileSync(OUT_HTML, buildHtml(data), 'utf-8');
    console.log(`done: raw=${data.rawCount}, filtered=${data.filteredCount}`);
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();