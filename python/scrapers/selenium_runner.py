from __future__ import annotations
"""
Selenium scraper returning a JSON-compatible dict with timing.
"""
import time
from datetime import datetime, timezone
from typing import Dict, Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def iso_now():
    return datetime.now(timezone.utc).isoformat()


def scrape(url: str, timeout: int) -> Dict[str, Any]:
    t0 = time.time()
    data = {}
    ok = False
    err = None
    driver = None
    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        title = driver.title
        html = driver.page_source
        data = {"title": title, "html": html}
        ok = True
    except Exception as e:
        err = str(e)
    finally:
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
    duration = time.time() - t0
    return {
        "ok": ok,
        "data": data,
        "error": err,
        "timestamps": {"observed_at": iso_now(), "duration_sec": duration},
    }
