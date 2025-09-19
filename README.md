# scraper_framework

A cross-method web scraping evaluation framework comparing five approaches across six metrics.

- Methods: Scrapy, requests+BeautifulSoup, Selenium, Puppeteer, Playwright
- Metrics (0-100 independent scoring): Accuracy, Completeness, Freshness, Redundancy, Throughput, Robustness

This repo includes:
- Python core evaluation engine and 3 scrapers (requests+BS4, Scrapy, Selenium)
- Node.js scrapers and CLI wrappers (Puppeteer, Playwright)
- Unified YAML config for scenarios and ground-truth
- Result aggregation to CSV/JSON and pretty terminal table

Quickstart:
- Create a scenario based on config/scenarios.example.yaml
- Run: python -m python.cli run --config config/scenarios.example.yaml --all
- Pretty table: python -m python.print_table

See README.hu.md for Hungarian documentation and usage.
