#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const { chromium } = require('playwright');

const ROOT = __dirname;
const DATA_JSON = path.join(ROOT, 'data.json');
const OUT_JSON = path.join(ROOT, 'hkex-disclosure.json');
const RAW_DIR = path.join(ROOT, 'hkex-raw');

function ensureDir(p) { fs.mkdirSync(p, { recursive: true }); }

function toNum(s) {
  if (!s) return null;
  const m = String(s).replace(/,/g, '').match(/([0-9]+(?:\.[0-9]+)?)/);
  if (!m) return null;
  const n = Number(m[1]);
  return Number.isFinite(n) ? n : null;
}

function parseFromText(txt) {
  const text = String(txt || '');
  // pdftotext 常把中文拆成「香 港 公 開 發 售」这种间隔，做一份去空白版本增强匹配
  const compact = text.replace(/[\s\u3000]+/g, '');

  const matchFirstNum = (rules, source = text) =>
    rules.map(rx => source.match(rx)?.[1]).map(toNum).find(Number.isFinite) ?? null;

  const offerPrice = matchFirstNum([
    /最終發售價[^\n]{0,200}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /最终发售价[^\n]{0,200}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /Final Offer Price[^\n]{0,240}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /發售價[^\n]{0,180}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /最終發售價HK\$([0-9]+(?:\.[0-9]+)?)/i,
    /最终发售价HK\$([0-9]+(?:\.[0-9]+)?)/i,
  ], compact.includes('最終發售價') || compact.includes('最终发售价') ? compact : text);

  const publicShares = matchFirstNum([
    /香港公開發售[^\n]{0,260}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /香港公开发售[^\n]{0,260}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /Hong Kong Public Offer(?:ing)?[^\n]{0,260}?([0-9,]+)\s*(?:Shares|H Shares)/i,
    /香港公開發售[^\n]{0,120}?股份數目[^\n]{0,80}?([0-9,]+)/i,
    /香港公开发售[^\n]{0,120}?股份数目[^\n]{0,80}?([0-9,]+)/i,
  ], compact.includes('香港公開發售') || compact.includes('香港公开发售') ? compact : text);

  const globalShares = matchFirstNum([
    /全球發售(?:股份)?[^\n]{0,260}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /全球发售(?:股份)?[^\n]{0,260}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /Global Offer(?:ing)?[^\n]{0,260}?([0-9,]+)\s*(?:Shares|H Shares)/i,
    /Offer Shares[^\n]{0,200}?([0-9,]+)\s*(?:Shares|H Shares)/i,
    /全球發售股份數目[^\n]{0,100}?([0-9,]+)/i,
    /全球发售股份数目[^\n]{0,100}?([0-9,]+)/i,
  ], compact.includes('全球發售') || compact.includes('全球发售') ? compact : text);

  const allotmentRatePct = matchFirstNum([
    /甲組\s*\(\s*\d+\s*手\s*\)[^\n]{0,140}?中籤率\s*([0-9]+(?:\.[0-9]+)?)\s*%/i,
    /甲组\s*\(\s*\d+\s*手\s*\)[^\n]{0,140}?中签率\s*([0-9]+(?:\.[0-9]+)?)\s*%/i,
    /一手[^\n]{0,100}?(?:中籤率|中签率)\s*([0-9]+(?:\.[0-9]+)?)\s*%/i,
    /allotment\s+ratio[^\n]{0,120}?([0-9]+(?:\.[0-9]+)?)\s*%/i,
    /一手(?:中籤率|中签率)([0-9]+(?:\.[0-9]+)?)%/i,
  ], compact.includes('中籤率') || compact.includes('中签率') ? compact : text);

  return {
    offerPriceHkd: offerPrice,
    publicShares,
    globalShares,
    publicGrossHkd: Number.isFinite(offerPrice) && Number.isFinite(publicShares) ? Math.round(offerPrice * publicShares) : null,
    internationalGrossHkd: Number.isFinite(offerPrice) && Number.isFinite(globalShares) ? Math.round(offerPrice * globalShares) : null,
    allotmentRatePct,
  };
}

async function fetchSearchRows(page, stockId) {
  const url = `https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockId=${stockId}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(2000);

  return await page.evaluate(() => {
    const out = [];
    const trs = Array.from(document.querySelectorAll('table tbody tr'));
    for (const tr of trs) {
      const tds = tr.querySelectorAll('td');
      const a = tr.querySelector('a[href*="/listedco/listconews/"]');
      const title = (a?.textContent || '').trim();
      const href = a?.getAttribute('href') || '';
      const date = (tds[0]?.textContent || '').trim();
      if (!title || !href) continue;
      out.push({ title, href, date });
    }
    return out;
  });
}

async function resolveStockIdsByName(name) {
  const q = encodeURIComponent(String(name || '').trim());
  if (!q) return [];
  const url = `https://www1.hkexnews.hk/search/partial.do?lang=ZH&type=A&name=${q}&market=SEHK&callback=callback`;
  try {
    const res = await fetch(url);
    const txt = await res.text();
    const m = txt.match(/callback\((.*)\)\s*;?\s*$/s);
    if (!m) return [];
    const arr = JSON.parse(m[1]);
    const ids = (Array.isArray(arr) ? arr : [])
      .map(x => String(x?.stockId || '').trim())
      .filter(Boolean);
    return [...new Set(ids)];
  } catch {
    return [];
  }
}

function pickBest(rows, stockName = '') {
  if (!rows?.length) return null;
  const n = String(stockName || '').trim();
  const score = (row) => {
    const t = String(row?.title || '');
    const d = String(row?.date || '');
    const y = Number((d.match(/(20\d{2})/) || [])[1] || 0);
    let x = 0;

    if (/最終發售價及配發結果公告|最终发售价及配发结果公告/i.test(t)) x += 260;
    if (/配發結果公告|配发结果公告|分配结果公告/i.test(t)) x += 220;
    if (/配發結果|配发结果|allotment results/i.test(t)) x += 150;
    if (/發售價|发售价|final offer price/i.test(t)) x += 80;
    if (/公告|announcement/i.test(t)) x += 20;
    if (n && t.includes(n)) x += 60;

    // 历史旧公告（同代码老公司）大幅降权
    if (y && y < 2020) x -= 260;
    else if (y && y < 2023) x -= 120;

    if (/聆訊後資料集|hearing|年報|月報表|翌日披露報表|翌日披露|回購|撤回上市地位|最後交易日期|關於.*交易所公告/i.test(t)) x -= 200;
    return x;
  };

  const sorted = [...rows].sort((a, b) => score(b) - score(a));
  const best = sorted[0];
  return score(best) > 80 ? best : null;
}

async function downloadFile(url, outPath) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`download failed: ${res.status} ${url}`);
  const buf = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(outPath, buf);
}

function pdfToText(pdfPath, txtPath) {
  try {
    execSync(`pdftotext -layout -enc UTF-8 ${JSON.stringify(pdfPath)} ${JSON.stringify(txtPath)}`, { stdio: 'pipe' });
    return fs.existsSync(txtPath);
  } catch {
    return false;
  }
}

async function run() {
  ensureDir(RAW_DIR);
  if (!fs.existsSync(DATA_JSON)) throw new Error('missing data.json');

  const argv = process.argv.slice(2);
  let limit = 30;
  const i = argv.indexOf('--limit');
  if (i >= 0 && argv[i + 1]) limit = Math.max(1, Number(argv[i + 1]) || 30);

  const data = JSON.parse(fs.readFileSync(DATA_JSON, 'utf-8'));
  const items = (data.items || []).slice(0, limit);

  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage();
  page.setDefaultTimeout(45000);

  const out = {};

  for (const it of items) {
    const code = String(it.code).padStart(5, '0');
    const stockIdByCode = String(Number(code));
    const name = String(it.name || '').trim();

    try {
      const idsByName = await resolveStockIdsByName(name);
      const candidateIds = [...new Set([stockIdByCode, ...idsByName])];

      let best = null;
      let pickedId = null;
      for (const sid of candidateIds) {
        const rows = await fetchSearchRows(page, sid);
        const p = pickBest(rows, name);
        if (!p) continue;
        if (!best || pickBest([p, best], name) === p) {
          best = p;
          pickedId = sid;
        }
      }

      if (!best) {
        out[code] = { status: 'not_found', rows: 0, triedStockIds: candidateIds };
        continue;
      }

      const href = best.href.startsWith('http') ? best.href : `https://www1.hkexnews.hk${best.href}`;
      const pdfPath = path.join(RAW_DIR, `${code}.pdf`);
      const txtPath = path.join(RAW_DIR, `${code}.txt`);
      await downloadFile(href, pdfPath);

      const ok = pdfToText(pdfPath, txtPath);
      const parsed = ok ? parseFromText(fs.readFileSync(txtPath, 'utf-8')) : {};

      out[code] = {
        status: 'ok',
        date: best.date,
        title: best.title,
        pdf: href,
        matchedStockId: pickedId,
        triedStockIds: candidateIds,
        ...parsed,
      };
    } catch (e) {
      out[code] = { status: 'error', error: String(e.message || e) };
    }
  }

  await browser.close();
  fs.writeFileSync(OUT_JSON, JSON.stringify({ generatedAt: new Date().toISOString(), limit, byCode: out }, null, 2));

  const okCount = Object.values(out).filter(v => v.status === 'ok').length;
  const parsedCount = Object.values(out).filter(v => v.status === 'ok' && Number.isFinite(v.offerPriceHkd) && Number.isFinite(v.publicShares) && Number.isFinite(v.globalShares)).length;
  const allotmentCount = Object.values(out).filter(v => v.status === 'ok' && Number.isFinite(v.allotmentRatePct)).length;
  console.log(`done: scanned=${items.length}, found=${okCount}, parsed=${parsedCount}, allotment=${allotmentCount}, out=${OUT_JSON}`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
