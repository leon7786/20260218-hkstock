# futu-sync — 港股 IPO 数据同步

> 抓取富途 `https://www.futunn.com/quote/hk/ipo` → 写入 `docs/index.html` → 推送到 GitHub Pages `https://leon7786.github.io/20260218-hkstock/`

## 同步机制（双通道）

| 通道 | 触发 | 时间 | 入口 |
|------|------|------|------|
| 本地 cron | crontab | 每天 08:00 BJT | `daily_sync_local.sh` |
| GitHub Actions | workflow | 每天 ~15:00 HKT | `.github/workflows/update-pending-ipo.yml` |

两通道独立运行，都执行相同的 6 步流水线，最后 commit + push 到 `origin master`。

## 核心流水线（6 步）

入口：`scripts/sync_futunn_to_pages.py`

```
[1/6] npm run sync:pending-ipo          → 抓待上市列表 → docs/pending-ipo.json
[2/6] add_new_ipo_rows_from_futunn.py   → Futunn 新股票补行到 index.html
[3/6] export_finished_ipo_dom_playwright.mjs → 翻页抓已上市 DOM → reports/futunn_finished_dom.json
[4/6] refresh_index_market_fields_from_dom_json.py → 行情字段写回 index.html
[5/6] fix_index_table_structure.py      → 规范化表结构，对齐列名
[6/6] refresh_index_meta.py             → 刷新页面顶部抓取时间/统计
```

## 文件清单

### 每日管道必备（12 文件）

```
daily_sync_local.sh               # cron 入口：sync → commit → push
scripts/sync_futunn_to_pages.py   # 编排器
scripts/export_pending_ipo_playwright.mjs        # 步骤1
scripts/add_new_ipo_rows_from_futunn.py          # 步骤2
scripts/export_finished_ipo_dom_playwright.mjs   # 步骤3
scripts/refresh_index_market_fields_from_dom_json.py  # 步骤4
scripts/fix_index_table_structure.py             # 步骤5
scripts/refresh_index_meta.py                    # 步骤6
package.json / package-lock.json  # npm: playwright
requirements-sync.txt             # pip: beautifulsoup4, requests
docs/                             # GitHub Pages 输出目录
```

### 辅助脚本（一次性工具，不在每日管道）

```
scripts/daily_sync_all.sh         # 旧版 sync 脚本（已废弃）
scripts/local_notify_tg.sh        # TG 通知，独立 cron 12:00
scripts/notify_dark_session_tg.py # TG 暗盘通知
scripts/fill_*.py (7个)           # 一次性数据回填（PDF/HKEX）
scripts/repair_*.py (3个)         # 一次性数据修复
scripts/compare_futunn_vs_site.py # 数据对比校验
scripts/audit_pdfs.py             # PDF 审计
scripts/quarantine_*.py (2个)     # 异常数据隔离
scripts/firecrawl_client.py       # Firecrawl 爬虫客户端
scripts/sync_ipo_pdf_kit.py       # PDF 套件同步
scripts/reorder_index_columns.py  # 列顺序调整
scripts/normalize_index_formats.py # 格式规范化
```

### 环境文件

```
env                               # TG bot token + chat id（不要提交 git）
reports/                          # 中间 JSON（gitignored）
logs/                             # 本地运行日志（gitignored）
```

## 本地运行

### 安装
```bash
npm install
npx playwright install --with-deps chromium
pip install beautifulsoup4 requests
```

### 跑完整同步
```bash
python3 scripts/sync_futunn_to_pages.py
```

### 只跑待上市
```bash
npm run sync:pending-ipo
```

### 手动 commit + push
```bash
export GIT_SSL_NO_VERIFY=1
git add docs/ scripts/ .github/workflows/ package.json package-lock.json requirements-sync.txt
git commit -m "chore(sync): daily futunn update $(date +%Y-%m-%d)"
git push origin master
```

## 当前 crontab

```
# hkstock local Futunn sync — 每天 08:00
0 8 * * * /root/Project/*20260527-hkstock-futu/daily_sync_local.sh >> /var/log/hkstock-daily-sync.log 2>&1

# hkstock TG notify — 每天 12:00
0 12 * * * /root/Project/*20260527-hkstock-futu/scripts/local_notify_tg.sh
```

## Git 配置

- Remote: `https://github.com/leon7786/20260218-hkstock.git`
- Auth: `gh auth git-credential` + custom credential helper（token 在 `/root/.config/gh/hosts.yml`）
- `GIT_SSL_NO_VERIFY=1`（本地 cron 脚本设置）

## 代理

本地 Playwright 脚本通过 HTTP 代理访问 Futunn：
```
PLAYWRIGHT_PROXY="http://127.0.0.1:2002|admin12|Dd;'2131801a"
```
设置在 `daily_sync_local.sh` 第 9 行。

## 已知问题 & 修复记录

### 2026-05-31：`git add reports/` 导致 cron 脚本中断

**现象**：cron 每天 08:00 执行，同步 6 步全部 OK，但 git commit + push 从未执行。日志停在 `git add` 警告后。

**根因**：`daily_sync_local.sh` 中 `git add docs/ reports/ scripts/ ...` 的 `reports/` 在 `.gitignore` 里，`git add reports/` 退出码 = 1，`set -e` 直接终止脚本。

**修复**：从 `git add` 移除 `reports/`（已在 2026-05-31 修好）。

### 注意：GitHub Actions workflow 无此 bug

`.github/workflows/update-pending-ipo.yml` 的 `git add` 本来就没有 `reports/`，不受影响。

## 故障排查

| 症状 | 优先检查 |
|------|----------|
| 待上市区域空白 | `docs/pending-ipo.json` 是否有内容；Futunn "待上市" tab DOM 是否变了 |
| 旧股票价格不更新 | `scripts/export_finished_ipo_dom_playwright.mjs` 翻页是否完整；`reports/futunn_finished_dom.json` 内容 |
| 首页结构/列错位 | `scripts/fix_index_table_structure.py` 列名是否匹配；最近是否改过列名 |
| cron 日志停在 git add | `git add` 命令里是否又加了 gitignored 路径 |
| push 失败 | `gh auth status`；token 是否过期；GIT_SSL_NO_VERIFY 是否设了 |

## 维护原则

1. **自动任务只做 Futunn 同步** — 不依赖 PDF / HKEX / 外部文件
2. **改列名必须同步改脚本** — `fix_index_table_structure.py`、`refresh_index_market_fields_from_dom_json.py`、`add_new_ipo_rows_from_futunn.py`、`reorder_index_columns.py`
3. **旧股不更新先看分页** — 不要先怀疑样式或 workflow 配置
