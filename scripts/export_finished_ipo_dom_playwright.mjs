#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const OUT = path.resolve('reports/futunn_finished_dom.json');

function nowCST() {
  return new Intl.DateTimeFormat('sv-SE', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  }).format(new Date()).replace(' ', ' ');
}

const PROXY = process.env.PLAYWRIGHT_PROXY || '';
const browser = await chromium.launch({ headless: true });
const ctxOpts = { locale: 'zh-CN' };
if (PROXY) {
  const [server, username, password] = PROXY.split('|');
  ctxOpts.proxy = username ? { server, username, password } : { server };
}
const context = await browser.newContext(ctxOpts);
const page = await context.newPage();
await page.goto('https://www.futunn.com/quote/hk/ipo', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(4000);
await page.mouse.wheel(0, 15000);
await page.waitForTimeout(1500);

async function extractCurrentPageRows() {
  return await page.evaluate(() => {
    const rows = [...document.querySelectorAll('a.list-item')]
      .map((el) => ({
        href: el.getAttribute('href') || '',
        txt: (el.innerText || '').split('\n').map((s) => s.trim()).filter(Boolean),
      }))
      .filter((r) => /\/stock\/\d{5}-HK/i.test(r.href) && r.txt.length >= 17 && /^\d{5}$/.test(r.txt[0] || ''))
      .map((r) => ({
        code: r.txt[0],
        name: r.txt[1],
        price: r.txt[2],
        firstDayPcr: r.txt[3],
        darkChangeNum: r.txt[4],
        darkChangeRatio: r.txt[5],
        ipoPriceChangeRatio: r.txt[6],
        ipoPrice: r.txt[7],
        changeRatio: r.txt[8],
        continuousRiseDayCnt: r.txt[9],
        tradeVolumn: r.txt[10],
        amount: r.txt[11],
        turnoverRate: r.txt[12],
        peStatic: r.txt[13],
        marketValue: r.txt[14],
        issueVolume: r.txt[15],
        listingDate: r.txt[16],
        href: r.href,
        raw: r.txt,
      }));
    const pages = [...document.querySelectorAll('span.item')]
      .map((el) => (el.textContent || '').trim())
      .filter((t) => /^\d+$/.test(t));
    return { rows, pages };
  });
}

const allByCode = new Map();
const seenPages = new Set();
while (true) {
  const { rows, pages } = await extractCurrentPageRows();
  for (const row of rows) allByCode.set(row.code, row);
  const currentPage = await page.evaluate(() => document.querySelector('span.item.current')?.textContent?.trim() || '1');
  seenPages.add(currentPage);
  const nextPage = pages.find((p) => !seenPages.has(p));
  if (!nextPage) break;
  await page.evaluate((pageNo) => {
    const el = [...document.querySelectorAll('span.item')].find((x) => (x.textContent || '').trim() === pageNo);
    if (!el) throw new Error(`page button not found: ${pageNo}`);
    el.scrollIntoView({ block: 'center', inline: 'center' });
    el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
  }, nextPage);
  await page.waitForTimeout(2200);
  await page.mouse.wheel(0, 15000);
  await page.waitForTimeout(1000);
}

const payload = { count: allByCode.size, items: [...allByCode.values()] };

const finalPayload = {
  generatedAt: nowCST(),
  timezone: 'Asia/Shanghai',
  sourceUrl: 'https://www.futunn.com/quote/hk/ipo',
  tab: '已上市',
  ...payload,
};
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(finalPayload, null, 2), 'utf8');
console.log(`wrote ${OUT} count=${finalPayload.count}`);
await browser.close();
