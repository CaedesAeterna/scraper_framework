// English-language CLI wrapper to call Node scrapers
import yargs from 'yargs';
import { hideBin } from 'yargs/helpers';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';
import path from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const argv = yargs(hideBin(process.argv))
  .command('puppeteer [url]', 'Run Puppeteer scraper', (y) => y
    .positional('url', { type: 'string', demandOption: true })
    .option('timeout', { type: 'number', default: 20000 })
  )
  .command('playwright [url]', 'Run Playwright scraper', (y) => y
    .positional('url', { type: 'string', demandOption: true })
    .option('timeout', { type: 'number', default: 20000 })
  )
  .demandCommand(1)
  .help()
  .argv;

const cmd = argv._[0];
const url = argv.url;
const timeout = argv.timeout;

const scriptMap = {
  puppeteer: path.join(__dirname, 'scrapers', 'puppeteer_scraper.js'),
  playwright: path.join(__dirname, 'scrapers', 'playwright_scraper.js'),
};

const script = scriptMap[cmd];
if (!script) {
  console.error(JSON.stringify({ ok: false, error: `unknown command ${cmd}` }));
  process.exit(1);
}

const child = spawn('node', [script, '--url', url, '--timeout', String(timeout)], { stdio: 'inherit' });
child.on('exit', (code) => process.exit(code || 0));
