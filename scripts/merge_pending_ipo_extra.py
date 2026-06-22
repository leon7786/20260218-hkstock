#!/usr/bin/env python3
"""Merge 绿鞋/公开发售/基石投资者 data back into pending-ipo.json after refresh.
Persists extra data in docs/pending-ipo-extra.json so it survives daily resyncs."""
import json
from pathlib import Path

ROOT = Path('/root/Projects/20260531-futu-sync')
JSON_PATH = ROOT / 'docs' / 'pending-ipo.json'
EXTRA_PATH = ROOT / 'docs' / 'pending-ipo-extra.json'

def load_extra():
    if EXTRA_PATH.exists():
        return json.loads(EXTRA_PATH.read_text('utf-8'))
    return {}

def save_extra(extra):
    EXTRA_PATH.write_text(json.dumps(extra, ensure_ascii=False, indent=2) + '\n', 'utf-8')

def merge():
    data = json.loads(JSON_PATH.read_text('utf-8'))
    extra = load_extra()
    items = data.get('items', [])
    
    # Ensure headers
    NEW_HEADERS = ['绿鞋', '公开发售', '基石投资者']
    for h in NEW_HEADERS:
        if h not in data['headers']:
            data['headers'].append(h)
    
    updated = False
    for item in items:
        code = item['code']
        if code in extra:
            for key in ['greenshoe', 'public_offering', 'cornerstone_count']:
                item[key] = extra[code].get(key, '—')
        else:
            # Initialize with placeholder
            for key in ['greenshoe', 'public_offering', 'cornerstone_count']:
                item[key] = '—'
        
        # Update fields array - last 3 elements should be the extra data
        # Fields has 7 from Futunn, we need to ensure 10 total
        while len(item['fields']) < 10:
            item['fields'].append('—')
        item['fields'][-3:] = [item['greenshoe'], item['public_offering'], item['cornerstone_count']]
        updated = True
    
    if updated:
        data['count'] = len(items)
        JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        print(f'✅ Merged extra data for {len(items)} pending IPOs')
    
    return extra

if __name__ == '__main__':
    extra = merge()
    for code, info in extra.items():
        print(f'  {code}: 绿鞋={info.get("greenshoe","—")[:20]:20s} 基石={info.get("cornerstone_count","—")}')
