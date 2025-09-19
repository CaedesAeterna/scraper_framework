from __future__ import annotations
"""
Lightweight Scrapy runner that fetches a single URL and extracts basic content.
"""
import time
import requests
from datetime import datetime, timezone
from typing import Dict, Any
from bs4 import BeautifulSoup


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def run_scrapy(url: str, timeout: int) -> Dict[str, Any]:
    """Scrapy-style scraper using requests+BS4 for reactor compatibility."""
    t0 = time.time()
    ok = False
    err = None
    data = {}
    try:
        # Use requests with Scrapy-style user agent
        headers = {'User-Agent': 'scraper-framework/0.1 (Scrapy-style)'}
        resp = requests.get(url, timeout=timeout, headers=headers)
        resp.raise_for_status()
        
        # Parse with BeautifulSoup using Scrapy-like selectors
        soup = BeautifulSoup(resp.text, 'lxml')
        title_tag = soup.select_one('title') or soup.select_one('h1')
        title = title_tag.get_text(strip=True) if title_tag else None
        
        data = {"title": title, "html": resp.text}
        ok = True
    except Exception as e:
        err = str(e)
    
    duration = time.time() - t0
    return {
        "ok": ok,
        "data": data,
        "error": err,
        "timestamps": {"observed_at": iso_now(), "duration_sec": duration},
    }
