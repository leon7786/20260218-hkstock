#!/usr/bin/env python3
"""Final update: reorder pending-ipo columns and compute 公开发售 amount.
Formula: 公开发售股数 × 发售价 = 公开发售金额(亿港元)"""
import json, re
from pathlib import Path

ROOT = Path('/root/Projects/20260531-futu-sync')
JSON_PATH = ROOT / 'docs' / 'pending-ipo.json'

# IPO data compiled from web research (Baidu/financial news)
# format: (total_global_shares, hk_public_shares, public_pct, price, greenshoe, cornerstone)
IPO_DETAILS = {
    "06106": {"global_shares": None, "hk_shares": None,  "public_pct": 5,   "price_h": 101.600, "greenshoe": "有", "cornerstone": 8,  "pub_amt": 0.53},
    "06067": {"global_shares": 149_500_000, "hk_shares": 14_952_500, "public_pct": 10,  "price_h": 8.980,    "greenshoe": "有", "cornerstone": 13, "pub_amt": 1.34},
    "06132": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 81.800,   "greenshoe": "有", "cornerstone": 6,  "pub_amt": 1.11},
    "02335": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 21.000,   "greenshoe": "有", "cornerstone": 3,  "pub_amt": 1.22},
    "06228": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 26.600,   "greenshoe": "有", "cornerstone": 11, "pub_amt": None},
    "06915": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 13.060,   "greenshoe": "有", "cornerstone": 1,  "pub_amt": None},
    "01956": {"global_shares": 14_834_600, "hk_shares": 741_800, "public_pct": 5,   "price_h": 60.700,   "greenshoe": "有", "cornerstone": 6,  "pub_amt": 0.45},
    "01688": {"global_shares": 812_000_000, "hk_shares": None, "public_pct": 10,  "price_h": 10.180,   "greenshoe": "",  "cornerstone": 19, "pub_amt": 8.27},
    "09630": {"global_shares": 12_838_650, "hk_shares": None,  "public_pct": 10,  "price_h": 252.730,  "greenshoe": "有", "cornerstone": 19, "pub_amt": None},
    "02672": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 20.280,   "greenshoe": "有", "cornerstone": 1,  "pub_amt": None},
    "02272": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 39.550,   "greenshoe": "",  "cornerstone": 0,  "pub_amt": None},
    "01191": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 114.000,  "greenshoe": "",  "cornerstone": 0,  "pub_amt": None},
    "02697": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 135.400,  "greenshoe": "",  "cornerstone": 0,  "pub_amt": None},
    "03952": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 85.500,   "greenshoe": "",  "cornerstone": 0,  "pub_amt": None},
    "06715": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 75.500,   "greenshoe": "",  "cornerstone": 0,  "pub_amt": None},
    "03661": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 85.200,   "greenshoe": "有", "cornerstone": 12, "pub_amt": None},
    "09637": {"global_shares": None, "hk_shares": None,  "public_pct": 10,  "price_h": 22.600,   "greenshoe": "",  "cornerstone": 0,  "pub_amt": None},
}

# If we have global shares but not HK shares, estimate: HK = global × public_pct
for code, d in IPO_DETAILS.items():
    if d["pub_amt"] is None and d["global_shares"] and d["price_h"]:
        hk_shares = d["hk_shares"] or (d["global_shares"] * d["public_pct"] / 100)
        pub_amt_hkd = hk_shares * d["price_h"]
        d["pub_amt"] = round(pub_amt_hkd / 100_000_000, 2)  # convert to 亿

# Load current data
data = json.loads(JSON_PATH.read_text('utf-8'))
items = data.get('items', [])

FUTUNN_HEADERS = ['招股价', '最小申购金额', '中签率', '申购截止日期', '公布中签', '富途暗盘', '上市日期']

# Build new headers
reordered_headers = ['基石投资者', '绿鞋', '公开发售']
reordered_headers.extend(FUTUNN_HEADERS)
data['headers'] = ['代码', '股票名称'] + reordered_headers

# Update items
for item in items:
    code = item['code']
    old_fields = item.get('fields', [])
    futunn_fields = old_fields[:7] if len(old_fields) >= 7 else ['—'] * 7
    
    detail = IPO_DETAILS.get(code, {})
    
    # 基石: just number
    cs = detail.get('cornerstone', 0)
    cs_display = str(cs) if cs > 0 else ''
    
    # 绿鞋: "有" or blank
    gs = detail.get('greenshoe', '')
    gs_display = '有' if gs else ''
    
    # 公开发售: calculated amount
    pub = detail.get('pub_amt')
    if pub is not None and pub > 0:
        pub_display = f'{pub}亿'
    else:
        pub_display = '—'
    
    item['fields'] = [cs_display, gs_display, pub_display] + futunn_fields
    
    # Clean old extra keys
    for k in ['greenshoe', 'public_offering', 'cornerstone_count', 
              'cornerstone_display', 'greenshoe_display', 'public_offering_display']:
        item.pop(k, None)
    
    print(f'{code} {item["name"]:12s} 基石={cs_display:2s} 绿鞋={gs_display:1s} 公开发售={pub_display}')

# Write back
data['count'] = len(items)
JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print(f'\n✅ Done. Headers: {", ".join(data["headers"])}')