const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const ARCHIVE_DIR = path.join(ROOT, 'archive');
const OUT_JSON = path.join(ROOT, 'archive-index.json');
const OUT_LOCAL_HTML = path.join(ROOT, 'archive-index.html');
const OUT_DOCS_HTML = path.join(ROOT, '..', 'docs', 'archive-index.html');

function readJsonSafe(p, fallback = null) {
  try { return JSON.parse(fs.readFileSync(p, 'utf-8')); } catch { return fallback; }
}

function fmtHkd(n) {
  if (!Number.isFinite(n)) return '待定';
  if (n >= 1e8) return `${(n / 1e8).toFixed(1)} 亿港元`;
  if (n >= 1e4) return `${(n / 1e4).toFixed(1)} 万港元`;
  return `${n.toFixed(1)} 港元`;
}

function fmtPct(n) {
  return Number.isFinite(n) ? `${n.toFixed(1)}%` : '待定';
}

function collect() {
  if (!fs.existsSync(ARCHIVE_DIR)) return [];
  const dirs = fs.readdirSync(ARCHIVE_DIR, { withFileTypes: true }).filter(d => d.isDirectory());
  const rows = [];
  for (const d of dirs) {
    const code = d.name;
    const summaryPath = path.join(ARCHIVE_DIR, code, 'summary.json');
    const summary = readJsonSafe(summaryPath, null);
    if (!summary) continue;
    const row = {
      code,
      status: summary.status || 'pending',
      sourceOfTruthDate: summary.sourceOfTruthDate || '待定',
      offerPriceHkd: Number(summary.offerPriceHkd),
      publicPct: Number(summary.publicPct),
      internationalPct: Number(summary.internationalPct),
      publicGrossHkd: Number(summary.publicGrossHkd),
      internationalGrossHkd: Number(summary.internationalGrossHkd),
      globalGrossHkd: Number(summary.globalGrossHkd),
      allotmentRatePct: Number(summary.allotmentRatePct)
    };
    rows.push(row);
  }
  return rows.sort((a,b)=>String(a.code).localeCompare(String(b.code)));
}

function renderRows(rows) {
  return rows.map(r => {
    const pub = Number.isFinite(r.publicGrossHkd) && Number.isFinite(r.publicPct)
      ? `${fmtPct(r.publicPct)}：${fmtHkd(r.publicGrossHkd)}`
      : '待定';
    const intl = Number.isFinite(r.internationalGrossHkd) && Number.isFinite(r.internationalPct)
      ? `${fmtPct(r.internationalPct)}：${fmtHkd(r.internationalGrossHkd)}`
      : '待定';
    return `<tr>
<td>${r.code}</td>
<td>${r.status}</td>
<td>${r.sourceOfTruthDate}</td>
<td>${Number.isFinite(r.offerPriceHkd) ? r.offerPriceHkd.toFixed(2) : '待定'}</td>
<td>${pub}</td>
<td>${intl}</td>
<td>${Number.isFinite(r.globalGrossHkd) ? fmtHkd(r.globalGrossHkd) : '待定'}</td>
<td>${Number.isFinite(r.allotmentRatePct) ? fmtPct(r.allotmentRatePct) : '待定'}</td>
</tr>`;
  }).join('\n');
}

function htmlTemplate(title, subtitle, tbody, useFetch = false) {
  const script = useFetch ? `<script>
fetch('./archive-index.json').then(r=>r.json()).then(d=>{
  document.getElementById('count').textContent = d.total;
  const rows = d.rows || [];
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = rows.map(r=>{
    const fmtHkd = n => Number.isFinite(n) ? (n>=1e8? (n/1e8).toFixed(1)+' 亿港元' : n>=1e4? (n/1e4).toFixed(1)+' 万港元' : n.toFixed(1)+' 港元') : '待定';
    const fmtPct = n => Number.isFinite(n) ? n.toFixed(1)+'%' : '待定';
    const pub = Number.isFinite(r.publicGrossHkd) && Number.isFinite(r.publicPct) ? fmtPct(r.publicPct)+'：'+fmtHkd(r.publicGrossHkd) : '待定';
    const intl = Number.isFinite(r.internationalGrossHkd) && Number.isFinite(r.internationalPct) ? fmtPct(r.internationalPct)+'：'+fmtHkd(r.internationalGrossHkd) : '待定';
    return '<tr><td>'+r.code+'</td><td>'+r.status+'</td><td>'+ (r.sourceOfTruthDate||'待定') +'</td><td>'+ (Number.isFinite(r.offerPriceHkd)? r.offerPriceHkd.toFixed(2):'待定') +'</td><td>'+pub+'</td><td>'+intl+'</td><td>'+(Number.isFinite(r.globalGrossHkd)?fmtHkd(r.globalGrossHkd):'待定')+'</td><td>'+(Number.isFinite(r.allotmentRatePct)?fmtPct(r.allotmentRatePct):'待定')+'</td></tr>';
  }).join('');
});
</script>` : '';

  return `<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>${title}</title><style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC",sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:16px}.wrap{max-width:1400px;margin:0 auto}.meta{color:#94a3b8;margin-bottom:10px}table{width:100%;border-collapse:collapse;background:#0b1222}th,td{border-bottom:1px solid #1e293b;padding:8px 10px;text-align:left;font-size:13px;white-space:nowrap}th{background:#111b33}.ok{color:#34d399}.pending{color:#fbbf24}</style></head><body><div class="wrap"><h1>${title}</h1><div class="meta">${subtitle}｜总数：<span id="count">${useFetch ? '加载中' : tbody.match(/<tr>/g)?.length || 0}</span></div><table><thead><tr><th>代码</th><th>状态</th><th>口径日期</th><th>发售价</th><th>公开募资</th><th>国际发售</th><th>全球募资</th><th>中签率</th></tr></thead><tbody id="tbody">${useFetch ? '' : tbody}</tbody></table></div>${script}</body></html>`;
}

(function main(){
  const rows = collect();
  const payload = { generatedAt: new Date().toISOString(), total: rows.length, rows };
  fs.writeFileSync(OUT_JSON, JSON.stringify(payload, null, 2), 'utf-8');

  const tbody = renderRows(rows);
  fs.writeFileSync(OUT_LOCAL_HTML, htmlTemplate('IPO 建档索引（本地实时读取 archive-index.json）', '本地页面：以建档数据为单一来源', tbody, true), 'utf-8');
  fs.writeFileSync(OUT_DOCS_HTML, htmlTemplate('IPO 建档索引（GitHub 静态快照）', 'GitHub 页面：发布时已静态化，不依赖实时调用', tbody, false), 'utf-8');

  console.log(`done: archiveRows=${rows.length}`);
})();
