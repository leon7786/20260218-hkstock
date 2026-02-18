# IPO 建档驱动体系（archive-first）

## 目标
- 每个股票统一建档到 `archive/<code>/`
- 页面展示（公开募资 / 国际发售 / 中签率）**只读建档**，不再临时估算

## 目录结构

```text
ipo-live/
  archive/
    <code>/
      summary.json
      sources.json
      raw/
        source_index.json
```

### summary.json 字段（上市前一日口径）
- offerPriceHkd
- globalShares, publicShares, internationalShares
- publicPct, internationalPct
- globalGrossHkd, publicGrossHkd, internationalGrossHkd
- listingExpensesHkd, netProceedsHkd
- allotmentRatePct
- publicSubscriptionMultiple, internationalSubscriptionMultiple
- validApplications, successfulApplications
- boardLot
- sourceOfTruthDate
- status (`verified | partial | pending`)

### sources.json 字段要求
每条来源都包含：
- url
- fetchedAt
- sourceType
- credibility
- extractedFields

## 脚本

### 1) 单票建档
```bash
node build_archive_for_code.js <code>
# 可选
node build_archive_for_code.js <code> --tolerance 0.03
```

规则：
- HKEX 检索入口作为主来源
- 至少两个辅源（futunn / aastocks / sina）
- 关键字段需 >=2 源接近（默认误差 <=3%）才可标记为 verified
- 否则标记 partial / pending，并在 `raw/source_index.json` 记录原因

### 2) 批量建档
```bash
node build_archive_batch.js --limit 20
```

- 从 `data.json` 读取代码顺序批量建档
- 输出统计：verified / partial / pending

## 页面生成逻辑

```bash
node scrape_futunn_ipo.js
```

- `公开募资 / 国际发售 / 中签率` 仅读取 `archive/<code>/summary.json`
- 仅 `status=verified` 且字段完整时展示数值
- 无档案或字段不达标显示“待定”

## 03858 样板
- 已内置在 `build_archive_for_code.js` 的 `SAMPLE_OVERRIDES["03858"]`
- 作为全字段高质量模板，可直接产出 `archive/03858/*`
