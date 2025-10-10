"""Utilities to extract and normalize visible text from HTML for comparison."""
from bs4 import BeautifulSoup
import re


def normalize_html_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # remove non-visible elements
    for tag in soup(['script', 'style', 'noscript']):
        tag.extract()

    text = soup.get_text(separator=' ', strip=True)
    # collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
