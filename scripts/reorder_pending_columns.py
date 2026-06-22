#!/usr/bin/env python3
"""Reorder pending-ipo columns and compute 公开发售 amount in 亿元.
Uses oversubscription ratio to back-calculate actual public offering size.
New column order: 基石投资者 | 绿鞋(有/空) | 公开发售(亿元) | 招股价 | ..."""
import json, re
from pathlib import Path

ROOT = Path('/root/Projects/20260531-futu-sync')
JSON_PATH = ROOT / 'docs' / 'pending-ipo.json'
EXTRA_PATH = ROOT / 'docs' / 'pending-ipo-extra.json'

# Extra data with oversubscription info
EXTRA_DATA = {
    "06106": {"greenshoe": "有，15%超额配股权", "oversub": "500倍", "margin": "267亿", "public_pct": "5%", "ipo_size": "10.67亿"},
    "06067": {"greenshoe": "有，15%超额配股权", "oversub": "303.5倍", "margin": "408亿", "public_pct": "10%", "ipo_size": "—"},
    "06132": {"greenshoe": "有，15%超额配股权", "oversub": "1166倍", "margin": "1298亿", "public_pct": "10%", "ipo_size": "—"},
    "02335": {"greenshoe": "有，15%超额配股权", "oversub": "646倍", "margin": "789亿", "public_pct": "10%", "ipo_size": "—"},
    "06228": {"greenshoe": "有，15%超额配股权", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "06915": {"greenshoe": "有，超额配股权", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "01956": {"greenshoe": "有", "oversub": "346倍", "margin": "—", "public_pct": "5%", "ipo_size": "—"},
    "01688": {"greenshoe": "无", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "09630": {"greenshoe": "有，15%超额配股权", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "02672": {"greenshoe": "有，15%超额配股权", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "02272": {"greenshoe": "—", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "01191": {"greenshoe": "—", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "02697": {"greenshoe": "—", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "03952": {"greenshoe": "—", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "06715": {"greenshoe": "—", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "03661": {"greenshoe": "有，15%超额配股权(绿鞋)，约6.90亿港元", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
    "09637": {"greenshoe": "—", "oversub": "—", "margin": "—", "public_pct": "10%", "ipo_size": "—"},
}

def parse_num(s):
    """Parse a number string like '267亿' or '500倍' to float."""
    s = str(s).replace(',', '')
    m = re.search(r'(\d+(?:\.\d+)?)', s)
    return float(m.group(1)) if m else 0

def calc_public_amount(code, name):
    """Calculate public offering amount in 亿港元."""
    extra = EXTRA_DATA.get(code, {})
    ipo_size = extra.get('ipo_size', '—')
    oversub = extra.get('oversub', '—')
    margin = extra.get('margin', '—')
    pub_pct = extra.get('public_pct', '10%')
    
    pct = parse_num(pub_pct) / 100  # e.g. 10% → 0.1
    
    # Method 1: If we have IPO size, calculate directly
    if ipo_size != '—':
        total = parse_num(ipo_size)
        amt = total * pct
        return round(amt, 2)
    
    # Method 2: Back-calculate from margin + oversubscription
    if margin != '—' and oversub != '—':
        margin_amt = parse_num(margin)
        oversub_times = parse_num(oversub)
        # Actually public offering = margin / (oversub_times + 1)
        # But oversub is usually expressed as 'N倍' meaning the subscription ratio
        # 公开发售 = 孖展金额 / (超购倍数 + 1) × (公开发售比例/总比例假设)
        # Simplified: the margin subscription is for the public tranche only
        # So: 公开发售实际金额 = 孖展金额 / 超购倍数
        pub_amt = margin_amt / oversub_times if oversub_times > 0 else 0
        if pub_amt > 0:
            return round(pub_amt, 2)
    
    # Method 3: Check the previous text data for any extractable amount
    old_extra = json.loads(EXTRA_PATH.read_text('utf-8')) if EXTRA_PATH.exists() else {}
    old_pub = old_extra.get(code, {}).get('public_offering', '')
    m = re.search(r'(\d+(?:\.\d+)?)\s*亿', old_pub)
    if m:
        return float(m.group(1))
    
    return None  # Can't calculate

# Load data
data = json.loads(JSON_PATH.read_text('utf-8'))
items = data.get('items', [])

FUTUNN_HEADERS = ['招股价', '最小申购金额', '中签率', '申购截止日期', '公布中签', '富途暗盘', '上市日期']

# Build new headers
reordered_headers = ['基石投资者', '绿鞋', '公开发售']
reordered_headers.extend(FUTUNN_HEADERS)

# Update headers in JSON
data['headers'] = ['代码', '股票名称'] + reordered_headers
assert len(data['headers']) == 2 + 7 + 3  # code+name + 3 new + 7 futunn = 12

# Update items
for item in items:
    code = item['code']
    name = item['name']
    old_fields = item.get('fields', [])
    futunn_fields = old_fields[:7] if len(old_fields) >= 7 else ['—'] * 7
    
    extra = EXTRA_DATA.get(code, {})
    
    # 基石投资者: just the number
    gs_text = extra.get('greenshoe', '—')
    cs_display = ''
    if 'cornerstone' in item:
        cs_old = str(item.get('cornerstone_count', ''))
        cs_display = re.sub(r'[^0-9]', '', cs_old)
    old_extra = json.loads(EXTRA_PATH.read_text('utf-8')) if EXTRA_PATH.exists() else {}
    cs_old = old_extra.get(code, {}).get('cornerstone_count', '')
    cs_display = re.sub(r'[^0-9]', '', cs_old) if cs_old != '—' else ''
    
    # 绿鞋: show "有" if greenshoe exists, blank otherwise
    gs_simple = '有' if gs_text not in ('—', '无', '') else ''
    
    # 公开发售: calculate amount in 亿元
    pub_amt = calc_public_amount(code, name)
    if pub_amt is not None and pub_amt > 0:
        pub_display = f'{pub_amt}亿'
    else:
        pub_display = '—'
    
    print(f'{code} {name:12s} 基石={cs_display:2s} 绿鞋={gs_simple:1s} 公开发售={pub_display}')
    
    item['fields'] = [cs_display, gs_simple, pub_display] + futunn_fields

# Clean up old extra fields from items
for item in items:
    for k in ['greenshoe', 'public_offering', 'cornerstone_count', 'cornerstone_display', 'greenshoe_display', 'public_offering_display']:
        item.pop(k, None)

# Write back
data['count'] = len(items)
JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print(f'\n✅ Done. Columns: {", ".join(data["headers"])}')