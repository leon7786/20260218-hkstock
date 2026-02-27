#!/usr/bin/env python3
"""Minimal Firecrawl client (search + scrape) for hkstock web-fill.

We keep this as a tiny wrapper so fill_index_from_web.py can use Firecrawl without depending on
OpenClaw's skill runtime.

Env:
  FIRECRAWL_API_KEY

API:
  https://api.firecrawl.dev/v1/search
  https://api.firecrawl.dev/v1/scrape
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import List, Optional


class FirecrawlError(RuntimeError):
    pass


@dataclass
class SearchHit:
    url: str
    title: str = ""
    description: str = ""


def _post_json(url: str, payload: dict, timeout: int = 60) -> dict:
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        raise FirecrawlError("FIRECRAWL_API_KEY not set")

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "ignore")
            return json.loads(body)
    except Exception as e:
        raise FirecrawlError(str(e))


def search(query: str, *, limit: int = 6, lang: str = "zh", country: str = "hk", timeout: int = 60) -> List[SearchHit]:
    j = _post_json(
        "https://api.firecrawl.dev/v1/search",
        {"query": query, "limit": limit, "lang": lang, "country": country},
        timeout=timeout,
    )
    if not j.get("success"):
        raise FirecrawlError(f"search failed: {j}")
    hits = []
    for item in (j.get("data") or []):
        url = (item or {}).get("url")
        if not url:
            continue
        hits.append(
            SearchHit(
                url=url,
                title=(item or {}).get("title") or "",
                description=(item or {}).get("description") or "",
            )
        )
    return hits


def scrape(url: str, *, only_main: bool = True, timeout: int = 90) -> str:
    j = _post_json(
        "https://api.firecrawl.dev/v1/scrape",
        {"url": url, "formats": ["markdown"], "onlyMainContent": bool(only_main)},
        timeout=timeout,
    )
    if not j.get("success"):
        raise FirecrawlError(f"scrape failed: {j}")
    data = j.get("data") or {}
    md = data.get("markdown") or ""
    return md
