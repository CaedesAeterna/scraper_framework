from __future__ import annotations
"""
Requests + BeautifulSoup scraper returning a JSON-compatible dict.
"""
import time
from datetime import datetime, timezone
from typing import Dict, Any

import requests
from bs4 import BeautifulSoup


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def scrape(url: str, timeout: int) -> Dict[str, Any]:
    t0 = time.time()
    data = {}
    ok = False
    err = None
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "scraper-framework/0.1"})
        resp.raise_for_status()
        html = resp.text
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else None
        data = {"title": title, "html": html}
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
