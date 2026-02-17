const fs = require('fs');
const path = require('path');
const { chromium } = require('../node_modules/playwright-core');

const OUT_DIR = __dirname;
const OUT_JSON = path.join(OUT_DIR, 'data.json');
const OUT_HTML = path.join(OUT_DIR, 'index.html');

const headers = [
  '代码','股票名称','价格','首日涨幅','暗盘涨跌额','暗盘涨跌幅','累计涨幅','发行价','涨跌幅','连涨天数','成交量','成交额','换手率','市盈率(静)','总市值','发行量','上市日期'
];

function isEtfName(name = '') {
  const n = String(name).toUpperCase();
  return n.includes('ETF') || n.includes('ETP') || n.includes('杠杆') || n.includes('反向');
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

  const filtered = all.filter(r => r.code && r.name && !isEtfName(r.name));

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
  const rowsHtml = data.items.map(r => {
    const tds = [
      `<td class="code">${r.code}</td>`,
      `<td class="name">${r.name}</td>`,
      ...headers.slice(2).map((_, i) => `<td>${r.values[i] ?? '-'}</td>`)
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
th{position:sticky;top:0;background:#111b33;z-index:1}
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
        <tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr>
      </thead>
      <tbody>
        ${rowsHtml}
      </tbody>
    </table>
  </div>
</div>
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