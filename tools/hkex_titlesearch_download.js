const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
async function ensureDir(p){ await fs.promises.mkdir(p,{recursive:true}); }

const TARGETS = [
  // 配發結果 / Allotment Results (最关键)
  { filename:'配發結果.pdf', patterns:[
    /配發結果/,
    /分配結果公告/,
    /配發結果公告/,
    /結果公告/,
    /Allotment\s*Results/i,
    /Results\s*of\s*Allocation/i,
    /Results\s*of\s*Allocations/i,
    /Results\s*of\s*allocations\s*in\s*the\s*Hong\s*Kong\s*Public\s*Offering/i,
  ] },
  { filename:'上市文件.pdf', patterns:[/上市文件/,/全球發售/,/Prospectus/i] },
  { filename:'正式通告.pdf', patterns:[/正式通告/,/Formal\s*Notice/i] },
  { filename:'穩價期終.pdf', patterns:[/穩定價格.*期.*結束/,/穩定價格行動/,/Stabil/i] },
  { filename:'綠鞋悉行.pdf', patterns:[/超額配股權.*行使/,/over-?allotment/i] },
  { filename:'調整權.pdf', patterns:[/發售量調整權/,/offer size adjustment/i] },
];

function scoreText(text, pats){
  return pats.reduce((s,p)=>s+(p.test(text)?1:0),0);
}

(async()=>{
  const code = process.argv[2];
  const name = process.argv.slice(3).join(' ');
  if(!code || !name){
    console.error('Usage: node tools/hkex_titlesearch_download.js <code5> <name>');
    process.exit(1);
  }

  const outDir = path.join('docs', `${code} ${name}`);
  await ensureDir(outDir);

  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();

  await page.goto('https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK', {
    waitUntil: 'networkidle', timeout: 90000,
  });

  // Stock picker
  await page.click('#searchStockCode');
  await page.keyboard.type(code, { delay: 110 });
  await page.waitForSelector('#autocomplete-list-0 tbody tr', { timeout: 8000 });
  const rows = page.locator('#autocomplete-list-0 tbody tr');
  const n = await rows.count();
  let picked = false;
  for (let i=0;i<n;i++){
    const t = (await rows.nth(i).innerText()).trim();
    if (new RegExp(`^${code}\\b`).test(t)) { await rows.nth(i).click(); picked = true; break; }
  }
  if (!picked && n>0) await rows.first().click();
  await sleep(500);

  // apply filters
  await page.fill('#searchTitle','');
  await page.click('a.filter__btn-applyFilters-js');
  await sleep(2500);

  const items = await page.evaluate(() => {
    const trs = [...document.querySelectorAll('table tbody tr')];
    const out = [];
    for (const tr of trs){
      const text = tr.innerText.replace(/\s+/g,' ').trim();
      const a = tr.querySelector('a[href*=".pdf"]');
      if (!a) continue;
      const href = a.getAttribute('href') || '';
      out.push({ text, href: href.startsWith('http') ? href : new URL(href, location.href).href });
    }
    return out;
  });

  const downloaded = [];
  const used = new Set();

  for (const t of TARGETS){
    let best = null; let bestScore = 0;
    for (const it of items){
      if (used.has(it.href)) continue;
      const s = scoreText(it.text, t.patterns);
      if (s > bestScore){ bestScore = s; best = it; }
    }
    if (best && bestScore > 0){
      const resp = await ctx.request.get(best.href, { timeout: 60000 });
      if (resp.ok()){
        const buf = await resp.body();
        await fs.promises.writeFile(path.join(outDir, t.filename), buf);
        downloaded.push({ filename: t.filename, url: best.href, text: best.text });
        used.add(best.href);
      }
    }
  }

  const readme = [
    `# ${code} ${name} — HKEXnews PDFs`,
    '',
    '來源入口：<https://www.hkexnews.hk/index_c.htm>',
    '流程：披露易標題搜尋（按股票代號選中標的）',
    '',
    '## 下載清單'
  ];
  for (const t of TARGETS){
    const hit = downloaded.find(x=>x.filename===t.filename);
    readme.push(`- \`${t.filename}\``);
    readme.push(`  - URL: ${hit ? hit.url : '(未找到)'}`);
    if (hit) readme.push(`  - Match: ${hit.text}`);
  }
  await fs.promises.writeFile(path.join(outDir,'README.md'), readme.join('\n')+'\n', 'utf-8');

  console.log('DOWNLOADED', downloaded.length);
  downloaded.forEach(d=>console.log(d.filename, d.url));
  if (!downloaded.length){
    console.log('NOTE no matches from title rows; maybe not published yet or keyword mismatch');
  }

  await browser.close();
})();
