# Web Scraping Evaluation Framework - Complete Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture & Design](#architecture--design)
3. [Installation & Setup](#installation--setup)
4. [Core Concepts](#core-concepts)
5. [Configuration Guide](#configuration-guide)
6. [Scraping Methods](#scraping-methods)
7. [Evaluation Metrics](#evaluation-metrics)
8. [Pseudo Ground Truth System](#pseudo-ground-truth-system)
9. [Usage Examples](#usage-examples)
10. [Output & Results](#output--results)
11. [Troubleshooting](#troubleshooting)
12. [Research Applications](#research-applications)

---

## Project Overview

### What Is This Framework?

This is a **cross-method web scraping evaluation framework** that compares five different scraping approaches across six independent metrics. It's designed for researchers and developers who need to:

- **Compare scraping technologies** objectively
- **Measure performance** across accuracy, speed, and robustness dimensions
- **Conduct reproducible experiments** without manual ground truth
- **Identify optimal scraping methods** for different website types

### Key Features

- **5 Scraping Methods**: Requests+BeautifulSoup, Scrapy, Selenium, Puppeteer, Playwright
- **6 Independent Metrics**: Accuracy, Completeness, Freshness, Redundancy, Throughput, Robustness
- **Automatic Content Extraction**: No manual field definitions needed
- **Pseudo Ground Truth**: Cross-validation without human annotation
- **Leave-One-Out Evaluation**: Prevents tautological comparisons
- **YAML Configuration**: Simple, declarative scenario definitions

---

## Architecture & Design

### Project Structure

```
scraper_framework/
├── python/                      # Python evaluation engine
│   ├── __init__.py
│   ├── cli.py                   # Main CLI entry point
│   ├── evaluator.py             # Core evaluation logic
│   ├── metrics.py               # Metric calculations
│   ├── pseudo_ground_truth.py   # Consensus builder
│   ├── html_utils.py            # HTML utilities
│   └── scrapers/                # Python scrapers
│       ├── requests_bs.py       # Requests+BeautifulSoup
│       ├── scrapy_runner.py     # Scrapy wrapper
│       └── selenium_runner.py   # Selenium scraper
│
├── js/                          # Node.js scrapers
│   ├── index.js
│   └── scrapers/
│       ├── puppeteer_scraper.js
│       └── playwright_scraper.js
│
├── config/                      # Configuration files
│   ├── scenarios.yaml           # Your test scenarios
│   └── scenarios.example.yaml   # Example config
│
├── results/                     # Evaluation outputs
│   ├── results.json             # Detailed results
│   └── results.csv              # Tabular summary
│
├── results_raw/                 # Raw scraper outputs
│   └── raw_results_latest.json
│
├── main.py                      # Entry point
└── README.md
```

### Data Flow

```
┌─────────────┐
│ Config YAML │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│   CLI Runner    │ ◄── User Command
└────────┬────────┘
         │
         ├──► Run All Scrapers ──► Collect HTML
         │
         ▼
┌───────────────────┐
│ Pseudo GT Builder │ ◄── Multi-scraper consensus
└─────────┬─────────┘
          │
          ▼
┌──────────────────────┐
│ Leave-One-Out Setup  │ ◄── Exclude each scraper
└──────────┬───────────┘
           │
           ▼
┌──────────────┐
│  Evaluator   │ ◄── Compare extracted fields
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Metrics (6)  │ ◄── Compute 0-100 scores
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ JSON + CSV   │ ◄── Export results
└──────────────┘
```

---

## Installation & Setup

### Prerequisites

**Python 3.8+** and **Node.js 16+** required.

### Step 1: Install Python Dependencies

```bash
pip install requests beautifulsoup4 lxml scrapy selenium pyyaml tqdm pandas
```

### Step 2: Install Browser Drivers

For Selenium:
```bash
# ChromeDriver (must match your Chrome version)
# Download from: https://chromedriver.chromium.org/
# Or use webdriver-manager:
pip install webdriver-manager
```

### Step 3: Install Node.js Dependencies

```bash
cd js
npm install puppeteer playwright
```

### Step 4: Verify Installation

```bash
python check_env.py
```

---

## Core Concepts

### 1. Target

A **target** is a web page you want to scrape. Each target has:
- **URL**: The page to scrape
- **Name**: Identifier for results
- **Complexity**: Low/Medium/High (for analysis grouping)
- **Selectors** (optional): Manual CSS/XPath selectors

Example:
```yaml
- name: example_org
  url: https://example.org
  complexity: low
```

### 2. Method

A **method** is a scraping technology:
- `requests`: Fast HTTP client with BeautifulSoup parsing
- `scrapy`: High-performance scraping framework
- `selenium`: Full browser automation (Chrome headless)
- `puppeteer`: Chromium-based headless browser (Node.js)
- `playwright`: Multi-browser automation (Node.js)

### 3. Extraction Modes

**Manual Mode** (with selectors):
```yaml
selectors:
  title:
    css: "h1"
  price:
    css: ".price"
```

**Auto Mode** (no selectors):
- Automatically extracts 10+ content types
- Works on any website
- Includes: titles, paragraphs, links, images, lists, metadata

### 4. Pseudo Ground Truth (PGT)

Since manually creating ground truth is expensive, this framework uses **consensus** from multiple scrapers:

1. Run all 5 methods on a target
2. Build consensus from agreeing scrapers
3. Evaluate each scraper against others (leave-one-out)

**Example**: If 4/5 scrapers extract the same title, that becomes the "ground truth" for comparison.

### 5. Leave-One-Out (LOO) Evaluation

To avoid tautological 100% scores:
- When evaluating **Method A**, compare it to consensus from **Methods B, C, D, E**
- Method A is excluded from its own ground truth
- Prevents comparing results to themselves

---

## Configuration Guide

### Basic Configuration

```yaml
targets:
  - name: my_website
    url: https://example.com
    complexity: medium

# Global settings
sampling:
  repeats: 1              # Run each method once
  parallelism: 3          # Not currently used

# Pseudo ground truth settings
pseudo_ground_truth:
  enabled: true
  confidence_threshold: 0.6   # Min confidence to accept consensus
  min_consensus: 2            # Min scrapers that must agree

# Timeout budgets per method
time_budget:
  requests:
    timeout_seconds: 10
  scrapy:
    timeout_seconds: 10
  selenium:
    timeout_seconds: 20
  puppeteer:
    timeout_seconds: 20
  playwright:
    timeout_seconds: 20

# Text processing
parsing:
  text_normalization:
    strip: true           # Remove leading/trailing whitespace
    lower: false          # Don't convert to lowercase
```

### Advanced: Manual Selectors

When you need specific fields:

```yaml
targets:
  - name: product_page
    url: https://shop.example.com/product/123
    selectors:
      product_name:
        css: "h1.product-title"
      price:
        css: "span.price"
      description:
        xpath: "//div[@class='description']//p[1]"
      availability:
        css: ".stock-status"
```

### Multiple Targets Example

```yaml
targets:
  # Static content
  - name: documentation
    url: https://docs.example.com
    complexity: low

  # Dynamic content (needs JS)
  - name: dashboard
    url: https://app.example.com/dashboard
    complexity: high

  # API-like endpoint
  - name: api_data
    url: https://api.example.com/v1/users
    complexity: medium
```

---

## Scraping Methods

### 1. Requests + BeautifulSoup (`requests`)

**Technology**: HTTP client + HTML parser

**Characteristics**:
- ✅ Very fast (no browser overhead)
- ✅ Low memory usage
- ❌ No JavaScript execution
- ❌ Can't handle dynamic content

**Best For**: Static HTML pages, APIs, simple websites

### 2. Scrapy (`scrapy`)

**Technology**: Asynchronous scraping framework

**Characteristics**:
- ✅ Fastest for multiple pages
- ✅ Built-in rate limiting, retries
- ❌ No JavaScript execution
- ❌ Complex for single-page scraping

**Best For**: Large-scale scraping, crawling

### 3. Selenium (`selenium`)

**Technology**: Browser automation via WebDriver

**Characteristics**:
- ✅ Full JavaScript execution
- ✅ Handles dynamic content
- ❌ Slow (full browser)
- ❌ High resource usage

**Best For**: JavaScript-heavy sites, SPAs

### 4. Puppeteer (`puppeteer`)

**Technology**: Headless Chromium (Node.js)

**Characteristics**:
- ✅ Fast JavaScript execution
- ✅ Modern browser APIs
- ✅ Lower overhead than Selenium
- ❌ Chrome only

**Best For**: Modern web apps, Node.js environments

### 5. Playwright (`playwright`)

**Technology**: Multi-browser automation

**Characteristics**:
- ✅ Supports Chrome, Firefox, Safari
- ✅ Fast and reliable
- ✅ Modern APIs
- ❌ Larger installation

**Best For**: Cross-browser testing, production scraping

---

## Evaluation Metrics

All metrics are normalized to **0-100 scale** where higher is better.

### 1. Accuracy (0-100)

**Measures**: How similar extracted content is to consensus

**Calculation**:
- For each field, compute similarity to other scrapers
- Average across all fields
- Uses Jaccard similarity for text, exact match for numbers

**Example**:
```
Title extracted: "Example Domain"
Consensus:       "Example Domain"
Similarity:      1.0 (100%)

Description extracted: "This domain is established"
Consensus:            "This domain is for examples"
Similarity:           0.6 (60%)

Average Accuracy: 80%
```

### 2. Completeness (0-100)

**Measures**: Percentage of expected fields successfully extracted

**Calculation**:
```
Completeness = (Fields Present / Total Expected Fields) × 100
```

**Example**:
```
Expected fields: [title, description, image_count, links]
Extracted:       [title, description, image_count]
Completeness:    75%
```

### 3. Freshness (0-100)

**Measures**: How quickly scraper retrieves updated content

**Calculation**:
- Maps time lag between source update and observation
- 0 seconds lag → 100
- 7 days lag → 0
- Linear interpolation

**Note**: Requires `source_updated_at` timestamp in config (rarely used in practice).

### 4. Redundancy (0-100)

**Measures**: Absence of duplicate data

**Calculation**:
```
Redundancy Rate = 1 - (Unique Items / Total Items)
Score = 100 * (1 - min(Redundancy Rate / 0.5, 1.0))
```

**Use Case**: Detecting pagination issues, infinite scroll problems.

### 5. Throughput (0-100)

**Measures**: Pages scraped per second

**Calculation**:
- Maps pages/sec to 0-100 scale
- 0 pages/sec → 0
- 10+ pages/sec → 100

**Example Results**:
```
requests:   15 pages/sec → 100/100
selenium:    2 pages/sec →  20/100
```

### 6. Robustness (0-100)

**Measures**: Success rate across diverse targets

**Calculation**:
```
Error Rate = Failed Requests / Total Requests
Robustness = 100 * (1 - min(Error Rate / 0.5, 1.0))
```

---

## Pseudo Ground Truth System

### The Problem

Manual ground truth annotation is:
- **Time-consuming**: Hours per website
- **Subjective**: What counts as "correct"?
- **Brittle**: Websites change frequently

### The Solution

**Statistical Consensus**: If multiple independent scrapers agree, it's probably correct.

### How It Works

#### Phase 1: Consensus Building

Multiple scrapers extract content independently. The system:
1. Collects all field values from successful scrapers
2. Finds the most common value for each field
3. Calculates confidence scores using 4 strategies
4. Accepts values with confidence > 0.6 threshold

#### Phase 2: Leave-One-Out Evaluation

Each scraper is evaluated against consensus built **without** its own data:
- Method A compared to consensus from B, C, D, E
- Method B compared to consensus from A, C, D, E
- And so on...

This prevents tautological 100% scores.

### Confidence Scoring

Four strategies are combined:

1. **Simple Majority (40% weight)**: Agreeing scrapers / Total
2. **Weighted Vote (30% weight)**: Based on scraper reliability
3. **Pattern Validation (20% weight)**: Regex matching for known types
4. **Consistency Check (10% weight)**: String similarity

---

## Usage Examples

### Basic Usage

Run all methods with automatic evaluation:

```bash
python main.py run --config config/scenarios.yaml --all
```

### Pseudo Ground Truth Mode

Enable leave-one-out evaluation:

```bash
python main.py run --config config/scenarios.yaml --all --pseudo-ground-truth
```

### Specific Methods Only

Test just browser-based methods:

```bash
python main.py run --config config/scenarios.yaml --methods selenium puppeteer playwright
```

### Without Saving Raw HTML

Save disk space:

```bash
python main.py run --config config/scenarios.yaml --all --no-raw
```

### View Results Table

Pretty-print results:

```bash
python python/print_table.py
```

### Diagnostic Mode

Debug evaluation issues:

```bash
python diagnostic_script.py
```

---

## Output & Results

### 1. results.json

Complete evaluation results with metadata including metrics, evaluation type, extracted fields, and timestamps.

### 2. results.csv

Tabular format for analysis with columns: target, url, method, ok, accuracy, completeness, freshness, redundancy, throughput, robustness, observed_at.

### 3. raw_results_latest.json

Raw HTML and scraper outputs for debugging and reprocessing.

---

## Troubleshooting

### Problem: All scores are 100%

**Cause**: Tautological comparison (comparing results to themselves)

**Solution**:
```bash
python diagnostic_script.py
```

Look for tautological warnings. Ensure `--pseudo-ground-truth` flag is set and minimum 2 successful scrapers per target.

### Problem: All accuracy scores are 0%

**Cause**: No fields extracted from HTML

**Solution**: Check raw results for empty `extracted_fields`. Verify HTML is being retrieved.

### Problem: Selenium fails with "ChromeDriver not found"

**Solution**:
```bash
pip install webdriver-manager
```

### Problem: "Insufficient scrapers" warnings

**Cause**: Not enough methods agreeing (need min 2)

**Solution**: Increase timeout values, check website accessibility, try simpler targets first.

---

## Research Applications

### Comparative Studies

Research questions this framework answers:

1. Which method is fastest for static content?
2. Do JavaScript frameworks require browser automation?
3. Is Playwright worth the overhead vs. Puppeteer?
4. How does website complexity affect scraper performance?

### Example Research Workflow

1. **Define Research Question**: "Are browser-based scrapers necessary for news websites?"
2. **Create Test Scenarios**: Define 20+ news site targets
3. **Run Experiments**: Execute with all methods
4. **Analyze Results**: Use pandas for statistical analysis
5. **Visualize**: Create comparison charts

### Publication-Ready Metrics

The framework provides:
- Reproducible experiments (YAML configs)
- Objective measurements (no human bias)
- Statistical validity (consensus-based ground truth)
- Comprehensive coverage (6 independent metrics)

---

## Best Practices

### 1. Start Small

Test with 1-2 targets before scaling.

### 2. Use Appropriate Timeouts

Fast scrapers need 5-10s, browser automation needs 20-30s.

### 3. Monitor Resource Usage

```bash
htop  # Watch memory/CPU while running
```

### 4. Version Control Configs

```bash
git add config/
git commit -m "Add experiment scenarios"
```

### 5. Document Experiments

Keep notes on hypothesis, methodology, and results.

---

## Conclusion

This framework provides a rigorous, reproducible method for evaluating web scraping technologies. By using pseudo ground truth and leave-one-out validation, it produces meaningful metrics without expensive manual annotation.

**Key Takeaways**:
- Automatic content extraction works for most websites
- Pseudo ground truth enables objective comparison
- Leave-one-out prevents inflated scores
- Six independent metrics capture different performance dimensions

For questions or contributions, see the project repository.
