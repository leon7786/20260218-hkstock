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

  const offerPrice = [
    /最終發售價[^\n]{0,120}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /Final Offer Price[^\n]{0,160}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
    /發售價[^\n]{0,120}?HK\$\s*([0-9]+(?:\.[0-9]+)?)/i,
  ].map(rx => text.match(rx)?.[1]).map(toNum).find(Number.isFinite) ?? null;

  const publicShares = [
    /香港公開發售[^\n]{0,120}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /香港公开发售[^\n]{0,120}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /Hong Kong Public Offering[^\n]{0,160}?([0-9,]+)\s*(?:Shares|H Shares)/i,
  ].map(rx => text.match(rx)?.[1]).map(toNum).find(Number.isFinite) ?? null;

  const globalShares = [
    /全球發售[^\n]{0,120}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /全球发售[^\n]{0,120}?([0-9,]+)\s*股(?:H股|股份)?/i,
    /Offer Shares[^\n]{0,160}?([0-9,]+)\s*(?:Shares|H Shares)/i,
  ].map(rx => text.match(rx)?.[1]).map(toNum).find(Number.isFinite) ?? null;

  return {
    offerPriceHkd: offerPrice,
    publicShares,
    globalShares,
    publicGrossHkd: Number.isFinite(offerPrice) && Number.isFinite(publicShares) ? Math.round(offerPrice * publicShares) : null,
    internationalGrossHkd: Number.isFinite(offerPrice) && Number.isFinite(globalShares) ? Math.round(offerPrice * globalShares) : null,
  };
}

async function fetchSearchRows(page, stockId) {
  const url = `https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=zh&market=SEHK&stockId=${stockId}`;
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(2500);

  const rows = await page.evaluate(() => {
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

  return rows;
}

function pickBest(rows) {
  if (!rows || !rows.length) return null;
  const score = (t) => {
    const s = String(t || '');
    let x = 0;
    if (/配發結果|配发结果|allotment results/i.test(s)) x += 100;
    if (/公告|announcement/i.test(s)) x += 10;
    if (/聆訊後資料集|hearing/i.test(s)) x -= 20;
    return x;
  };
  return [...rows].sort((a, b) => score(b.title) - score(a.title))[0];
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
    const stockId = String(Number(code));

    try {
      const rows = await fetchSearchRows(page, stockId);
      const best = pickBest(rows);
      if (!best) {
        out[code] = { status: 'not_found', rows: 0 };
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
  console.log(`done: scanned=${items.length}, found=${okCount}, parsed=${parsedCount}, out=${OUT_JSON}`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
