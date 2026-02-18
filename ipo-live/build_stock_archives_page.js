#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const ARCHIVE_DIR = path.join(ROOT, 'stock-archives');
const DOCS_DIR = path.join(ROOT, 'docs');
const OUT_JSON = path.join(DOCS_DIR, 'stock-archives.json');
const OUT_HTML = path.join(DOCS_DIR, 'stock-archives.html');

function esc(s='') {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function parseTable(lines) {
  const rows = [];
  const tableLines = lines.filter(l => /^\|.*\|\s*$/.test(l.trim()));
  if (tableLines.length < 3) return rows;
  for (let i = 2; i < tableLines.length; i++) {
    const line = tableLines[i].trim();
    if (/^\|[-\s|:]+\|$/.test(line)) continue;
    const cols = line.split('|').slice(1, -1).map(c => c.trim());
    if (cols.length < 5) continue;
    rows.push({
      category: cols[0],
      field: cols[1],
      value: cols[2],
      sourceType: cols[3],
      source: cols[4]
    });
  }
  return rows;
}

function parseFile(fullPath) {
  const content = fs.readFileSync(fullPath, 'utf-8');
  const lines = content.split(/\r?\n/);
  const title = (lines.find(l => l.startsWith('# ')) || '').replace(/^#\s*/, '').trim();
  const codeMatch = title.match(/^(\d{5})/);
  const code = codeMatch ? codeMatch[1] : path.basename(fullPath).slice(0, 5);
  const rows = parseTable(lines);
  return { code, title, file: path.basename(fullPath), rows };
}

function buildHtml(items) {
  const cards = items.map(it => {
    const trs = it.rows.map(r => `<tr><td>${esc(r.category)}</td><td>${esc(r.field)}</td><td>${esc(r.value)}</td><td>${esc(r.sourceType)}</td><td>${esc(r.source)}</td></tr>`).join('');
    return `<details class="card"><summary><span class="code">${esc(it.code)}</span> ${esc(it.title)} <span class="count">${it.rows.length} 条</span></summary><div class="inner"><table><thead><tr><th>类别</th><th>字段</th><th>数值</th><th>来源类型</th><th>来源</th></tr></thead><tbody>${trs}</tbody></table></div></details>`;
  }).join('\n');

  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>IPO 建档详情（基于 TXT 静态生成）</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:16px}
.wrap{max-width:1600px;margin:0 auto}
a{color:#93c5fd}
.meta{color:#94a3b8;font-size:13px;margin:8px 0 12px}
.card{border:1px solid #334155;border-radius:10px;margin:12px 0;background:#0b1222}
summary{cursor:pointer;list-style:none;padding:10px 12px;font-weight:600}
summary::-webkit-details-marker{display:none}
.code{color:#93c5fd;font-weight:700;margin-right:8px}
.count{color:#94a3b8;font-weight:400;margin-left:8px}
.inner{padding:0 10px 10px 10px;overflow:auto}
table{width:100%;border-collapse:collapse;min-width:1200px}
th,td{border-bottom:1px solid #1e293b;padding:8px 10px;text-align:left;font-size:13px;white-space:nowrap}
th{position:sticky;top:0;background:#111b33}
</style>
</head>
<body>
<div class="wrap">
  <h1>IPO 建档详情（基于 TXT 静态生成）</h1>
  <div class="meta">总股票数：${items.length} ｜ 数据来源：stock-archives/*.txt ｜ 生成时间：${new Date().toLocaleString('zh-CN', {hour12:false})}</div>
  <div class="meta"><a href="./index.html">← 返回主页面</a></div>
  ${cards || '<p>暂无建档数据。</p>'}
</div>
</body>
</html>`;
}

function run() {
  fs.mkdirSync(DOCS_DIR, { recursive: true });
  const files = fs.existsSync(ARCHIVE_DIR)
    ? fs.readdirSync(ARCHIVE_DIR).filter(f => f.endsWith('.txt')).sort()
    : [];
  const items = files.map(f => parseFile(path.join(ARCHIVE_DIR, f)));
  fs.writeFileSync(OUT_JSON, JSON.stringify({ generatedAt: new Date().toISOString(), total: items.length, items }, null, 2));
  fs.writeFileSync(OUT_HTML, buildHtml(items), 'utf-8');
  console.log(`done: items=${items.length}, out=${OUT_HTML}`);
}

run();
