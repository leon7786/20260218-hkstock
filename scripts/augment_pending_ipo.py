#!/usr/bin/env python3
"""Augment pending-ipo.json with 绿鞋/公开发售/基石投资者 for each stock.
Searches web for each pending IPO and fills in the details."""
import json, re, time, sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import quote

ROOT = Path('/root/Projects/20260531-futu-sync')
JSON_PATH = ROOT / 'docs' / 'pending-ipo.json'

def ddg_search(query):
    """Search DuckDuckGo HTML, return text snippets."""
    url = f'https://html.duckduckgo.com/html/?q={quote(query)}'
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})
    try:
        body = urlopen(req, timeout=15).read().decode('utf-8', errors='replace')
    except Exception as e:
        return f'[search error: {e}]'
    # Extract result snippets
    snippets = []
    for m in re.finditer(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.DOTALL):
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if text:
            snippets.append(text)
    return snippets[:5] if snippets else ['[no results]']

def search_ipo_info(code, name):
    """Search for IPO info and extract 绿鞋/公开发售/基石."""
    info = {'greenshoe': '—', 'public_offering': '—', 'cornerstone_count': '—'}
    
    queries = [
        f'{code}.HK {name} 招股 绿鞋 公开发售 基石',
        f'{code} {name} IPO 招股价 绿鞋 超额配股权',
        f'港股 {code} {name} 招股说明书 基石投资者',
    ]
    
    all_text = ''
    for q in queries:
        snippets = ddg_search(q)
        all_text += '\n'.join(snippets) + '\n'
        time.sleep(1.5)
    
    # Extract 绿鞋 / 超额配股权
    gs_patterns = [
        r'绿鞋[：:\s]*(\d+[%％])',
        r'超额配股权[：:\s]*(\d+[%％])',
        r'超额配发[：:\s]*(\d+[%％])',
        r'绿鞋[：:\s]*(不超过[^，。]*?\d+[%％])',
        r'超额配[：:\s]*(不超过[^，。]*?\d+[%％])',
        r'(超额配股权|绿鞋).*?(不超过[^，。]*?\d+[%％])',
    ]
    for pat in gs_patterns:
        m = re.search(pat, all_text)
        if m:
            g = m.group(1) if m.lastindex == 1 else m.group(2)
            info['greenshoe'] = g.strip()
            break
    if info['greenshoe'] == '—':
        # Check for 15% which is the standard
        if re.search(r'超额配|绿鞋', all_text):
            info['greenshoe'] = '有(待确认)'
    
    # Extract 公开发售 / 国际发售
    pub_patterns = [
        r'公开发售[：:\s]*([^，。\n]{3,30})',
        r'公开发行[：:\s]*([^，。\n]{3,30})',
        r'香港公开发售[：:\s]*([^，。\n]{3,30})',
        r'公开发售部分[：:\s]*([^，。\n]{3,30})',
    ]
    for pat in pub_patterns:
        m = re.search(pat, all_text)
        if m:
            info['public_offering'] = m.group(1).strip()
            break
    
    # Extract 基石投资者 number
    cs_patterns = [
        r'基石投资者[共合]?[：:\s]*(\d+)',
        r'引入[了]?(\d+)[家名位个]基石',
        r'(\d+)[家名位个]基石投资者',
        r'基石.*?(\d+)[家名位个]',
    ]
    for pat in cs_patterns:
        m = re.search(pat, all_text)
        if m:
            info['cornerstone_count'] = m.group(1) + '家'
            break
    
    # Try to count cornerstone names
    cs_names = re.findall(r'([\u4e00-\u9fff]{2,10}?(?:基金|投资|资本|资产|集团|国际|银行|证券|保险|信托))[，\s、]*.*?基石', all_text)
    if cs_names and info['cornerstone_count'] == '—':
        info['cornerstone_count'] = f'{len(cs_names)}家'
    
    if info['cornerstone_count'] == '—':
        # Check if there's any mention
        if re.search(r'基石', all_text):
            info['cornerstone_count'] = '有(待确认)'
    
    return info

def main():
    data = json.loads(JSON_PATH.read_text('utf-8'))
    items = data.get('items', [])
    print(f'Total pending IPOs: {len(items)}')
    
    for i, item in enumerate(items):
        code = item['code']
        name = item['name']
        print(f'\n[{i+1}/{len(items)}] {code} {name}')
        
        info = search_ipo_info(code, name)
        print(f'  绿鞋: {info["greenshoe"]}')
        print(f'  公开发售: {info["public_offering"]}')
        print(f'  基石: {info["cornerstone_count"]}')
        
        item['greenshoe'] = info['greenshoe']
        item['public_offering'] = info['public_offering']
        item['cornerstone_count'] = info['cornerstone_count']
        
        # Add to fields array too for frontend rendering
        item['fields'].extend([info['greenshoe'], info['public_offering'], info['cornerstone_count']])
        
        # Update headers
        if 'headers' in data:
            for h in ['绿鞋', '公开发售', '基石投资者']:
                if h not in data['headers']:
                    data['headers'].append(h)
    
    # Write back
    data['count'] = len(items)
    JSON_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(f'\n✅ Updated pending-ipo.json with {len(items)} items')

if __name__ == '__main__':
    main()
