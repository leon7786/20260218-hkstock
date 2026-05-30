#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '..');
const outPath = path.join(repoRoot, 'docs', 'pending-ipo.json');
const sourceUrl = 'https://www.futunn.com/quote/hk/ipo';

function nowHK() {
  return new Date().toLocaleString('zh-CN', {
    timeZone: 'Asia/Hong_Kong',
    hour12: false,
  }).replace(/\//g, '-');
}

const PROXY = process.env.PLAYWRIGHT_PROXY || '';
const browser = await chromium.launch({ headless: true });
const ctxOpts = { locale: 'zh-CN', timezoneId: 'Asia/Hong_Kong' };
if (PROXY) {
  const [server, username, password] = PROXY.split('|');
  ctxOpts.proxy = username ? { server, username, password } : { server };
}
const context = await browser.newContext(ctxOpts);
const page = await context.newPage();

try {
  await page.goto(sourceUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.getByText('待上市', { exact: true }).click();
  await page.waitForTimeout(1500);

  const data = await page.evaluate(() => {
    const activeTab = [...document.querySelectorAll('.rank-item')].find((el) => el.classList.contains('active'))?.textContent?.trim() || null;

    const tables = [...document.querySelectorAll('section')]
      .map((section) => {
        const text = (section.textContent || '').replace(/\s+/g, ' ').trim();
        const anchors = [...section.querySelectorAll('a.list-item')];
        return { section, text, anchors };
      })
      .filter((x) => x.anchors.length > 0);

    const target = tables.find((x) => /招股价|最小申购金额|申购截止日期|富途暗盘|上市日期/.test(x.text)) || tables[0] || null;

    const headerTexts = target
      ? [...target.section.querySelectorAll('.content-head .text, .content-head .code, .content-head .name')]
          .map((el) => el.textContent.trim())
          .filter(Boolean)
      : [];

    const rows = (target ? target.anchors : [])
      .map((el) => {
        const href = el.getAttribute('href') || '';
        const text = el.innerText
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean);
        if (text.length < 8) return null;
        if (!/^\/?stock\/\d{5}-HK$/i.test(href)) return null;
        if (!/^\d{5}$/.test(text[0])) return null;
        return {
          code: text[0],
          name: text[1],
          fields: text.slice(2),
          href,
          raw: text,
        };
      })
      .filter(Boolean);

    return { activeTab, headerTexts, rows };
  });

  const payload = {
    generatedAt: nowHK(),
    timezone: 'Asia/Hong_Kong',
    sourceUrl,
    tab: data.activeTab || '待上市',
    headers: data.headerTexts,
    count: data.rows.length,
    items: data.rows,
  };

  await fs.writeFile(outPath, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  console.log(`wrote ${outPath} count=${payload.count}`);
} finally {
  await browser.close();
}
