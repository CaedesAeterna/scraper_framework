// Minimal Playwright scraper printing a single JSON line
import { chromium } from 'playwright';
import yargs from 'yargs';
import { hideBin } from 'yargs/helpers';

const argv = yargs(hideBin(process.argv))
  .option('url', { type: 'string', demandOption: true })
  .option('timeout', { type: 'number', default: 20000 })
  .argv;

// Convert timeout from seconds to milliseconds if it's too small
const timeoutMs = argv.timeout < 1000 ? argv.timeout * 1000 : argv.timeout;

(async () => {
  const start = Date.now();
  let browser;
  try {
    browser = await chromium.launch();
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto(argv.url, { timeout: timeoutMs, waitUntil: 'domcontentloaded' });
    const title = await page.title();
    const html = await page.content();
    const duration = (Date.now() - start) / 1000.0;
    const out = {
      ok: true,
      data: { title, html },
      error: null,
      timestamps: { observed_at: new Date().toISOString(), duration_sec: duration }
    };
    console.log(JSON.stringify(out));
  } catch (e) {
    const duration = (Date.now() - start) / 1000.0;
    console.log(JSON.stringify({ ok: false, data: {}, error: String(e), timestamps: { observed_at: new Date().toISOString(), duration_sec: duration } }));
  } finally {
    if (browser) await browser.close();
  }
})();
