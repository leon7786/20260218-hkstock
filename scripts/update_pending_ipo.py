#!/usr/bin/env python3
"""Update pending-ipo.json with 绿鞋/公开发售/基石投资者 data from web research."""
import json
from pathlib import Path

ROOT = Path('/root/Projects/20260531-futu-sync')
JSON_PATH = ROOT / 'docs' / 'pending-ipo.json'

# Web-researched data for each stock
IPO_DATA = {
    "06106": {"greenshoe": "有，15%超额配股权", "public_offering": "香港公开发售占5%，超购近500倍，孖展267亿港元", "cornerstone_count": "8家"},
    "06067": {"greenshoe": "有，15%超额配股权", "public_offering": "香港公开发售占10%，超购303.5倍，孖展408亿港元", "cornerstone_count": "13家"},
    "06132": {"greenshoe": "有，15%超额配股权", "public_offering": "香港发售占10%，超购1166倍，孖展1298亿港元", "cornerstone_count": "6家"},
    "02335": {"greenshoe": "有，15%超额配股权", "public_offering": "香港公开发售占10%，超购646倍，孖展789亿港元", "cornerstone_count": "3家"},
    "06228": {"greenshoe": "有，15%超额配股权", "public_offering": "香港公开发售占10%，招股价≤26.60港元", "cornerstone_count": "11家"},
    "06915": {"greenshoe": "有，超额配股权", "public_offering": "香港发售占10%，招股价9.33-13.06港元", "cornerstone_count": "1家"},
    "01956": {"greenshoe": "有，15%超额配股权，约1.35亿港元", "public_offering": "香港发售占5%，超购346倍，发售价60.70港元", "cornerstone_count": "6家"},
    "01688": {"greenshoe": "无", "public_offering": "香港公开发售占10%，发售价≤10.18港元", "cornerstone_count": "19家"},
    "09630": {"greenshoe": "有，15%超额配股权", "public_offering": "香港公开发售占10%，发售价240.09-252.73港元", "cornerstone_count": "19家"},
    "02672": {"greenshoe": "有，15%超额配股权", "public_offering": "香港发售占10%，发售价15.60-20.28港元", "cornerstone_count": "1家"},
    "02272": {"greenshoe": "—", "public_offering": "发售价39.55港元", "cornerstone_count": "0家"},
    "01191": {"greenshoe": "—", "public_offering": "—", "cornerstone_count": "—"},
    "02697": {"greenshoe": "—", "public_offering": "—", "cornerstone_count": "—"},
    "03952": {"greenshoe": "—", "public_offering": "—", "cornerstone_count": "—"},
    "06715": {"greenshoe": "—", "public_offering": "—", "cornerstone_count": "—"},
    "03661": {"greenshoe": "有，15%超额配股权(绿鞋)，约6.90亿港元", "public_offering": "香港公开发售占10%，发售价≤85.20港元", "cornerstone_count": "12家"},
    "09637": {"greenshoe": "—", "public_offering": "—", "cornerstone_count": "—"},
}

data = json.loads(JSON_PATH.read_text('utf-8'))
items = data.get('items', [])

NEW_HEADERS = ['绿鞋', '公开发售', '基石投资者']
for h in NEW_HEADERS:
    if h not in data['headers']:
        data['headers'].append(h)

for item in items:
    code = item['code']
    info = IPO_DATA.get(code, {})
    item['greenshoe'] = info.get('greenshoe', '—')
    item['public_offering'] = info.get('public_offering', '—')
    item['cornerstone_count'] = info.get('cornerstone_count', '—')
    item['fields'].extend([item['greenshoe'], item['public_offering'], item['cornerstone_count']])

data['count'] = len(items)
JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print(f'✅ Updated {len(items)} items with 绿鞋/公开发售/基石投资者')
for item in items:
    print(f'  {item["code"]} {item["name"]:12s} 绿鞋={item["greenshoe"][:20]:20s} 基石={item["cornerstone_count"]:6s}')