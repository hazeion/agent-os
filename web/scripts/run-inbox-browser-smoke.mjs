import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import puppeteer from 'puppeteer-core';

const port = Number(process.env.MENTAT_RUN_INBOX_TEST_PORT);
const width = Number(process.env.MENTAT_RUN_INBOX_TEST_WIDTH);
assert(Number.isInteger(port) && port > 0 && port < 65536 && [390, 1280].includes(width));
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true,
  args: process.env.MENTAT_CONTEXT_TEST_NO_SANDBOX === '1' ? ['--no-sandbox'] : [],
});
let page;
let stage = 'launch';
const responses = [];
const errors = [], failures = [];
try {
  page = await browser.newPage();
  await page.setViewport({ width, height: 900, deviceScaleFactor: 1 });
  await page.setRequestInterception(true);
  page.on('request', request => {
    if (new URL(request.url()).origin === `http://127.0.0.1:${port}`) void request.continue();
    else void request.abort();
  });
  page.on('pageerror', error => errors.push(error.message));
  page.on('requestfailed', request => failures.push([request.url(), request.failure()?.errorText]));
  page.on('response', response => { if (new URL(response.url()).pathname.startsWith('/api/')) responses.push([response.status(), new URL(response.url()).pathname]); });
  stage = 'home';
  await page.goto(`http://127.0.0.1:${port}/`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => Array.from(document.querySelectorAll('section[aria-label="Inbox attention"] a'))
    .some(link => link.textContent?.includes('Agent run failed')));
  const home = await page.$('section[aria-label="Inbox attention"] a[href^="/inbox?item="]');
  assert(home);
  stage = 'inbox';
  await home.click();
  await page.waitForFunction(() => location.pathname === '/inbox' &&
    document.querySelector('section[aria-label="Inbox item detail"] h2')?.textContent === 'Run outcome');
  const detail = 'section[aria-label="Inbox item detail"]';
  const before = await page.$eval(detail, node => node.innerText);
  assert(before.includes('Notice reference:') && before.includes('Run started:'));
  assert(before.includes('Source:') && before.includes('Agent Console'));
  assert.equal(await page.$(`${detail} a[href="/runs"]`), null);
  assert.equal(await page.$eval(detail, node => Array.from(node.querySelectorAll('button'))
    .some(button => button.textContent === 'Accept saved results')), false);
  stage = 'acknowledge';
  await page.locator(`${detail} ::-p-text(Acknowledge)`).click();
  await page.waitForFunction(() => Array.from(document.querySelectorAll('section[aria-label="Inbox item detail"] button'))
    .some(button => button.textContent === 'Dismiss notice'));
  await page.locator(`${detail} ::-p-text(Dismiss notice)`).click();
  stage = 'dismiss';
  await page.waitForFunction(() => document.querySelector('section[aria-label="Inbox item detail"]')?.textContent?.includes('Notice dismissed.'));
  const resolved = await page.$eval(detail, node => node.innerText);
  assert(resolved.includes('Outcome: Failed') && resolved.includes('Notice: Resolved'));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
  assert.deepEqual(errors, []);
  const output = resolve('../artifacts/run-inbox-acceptance'); await mkdir(output, { recursive: true });
  await page.screenshot({ path: resolve(output, `${width}.png`), fullPage: true });
  console.log(JSON.stringify({ width, runNotice: true, acknowledged: true, dismissed: true, overflow: false }));
} catch (error) {
  if (page) console.error(JSON.stringify({ stage, url: page.url(), responses: responses.slice(-30), errors, failures: failures.slice(-10),
    text: await page.evaluate(() => document.body.innerText.slice(-3000)) }));
  throw error;
} finally {
  await browser.close();
}
