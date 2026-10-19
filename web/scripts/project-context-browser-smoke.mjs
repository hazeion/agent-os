import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import puppeteer from 'puppeteer-core';

const port = Number(process.env.MENTAT_CONTEXT_TEST_PORT), width = Number(process.env.MENTAT_CONTEXT_TEST_WIDTH);
assert(Number.isInteger(port) && port > 0 && port < 65536 && [390, 1280].includes(width));
// Opt-in for the disposable CI runner, whose user namespaces are disabled.
const browser = await puppeteer.launch({ executablePath: process.env.CHROME_PATH, headless: true,
  args: process.env.MENTAT_CONTEXT_TEST_NO_SANDBOX === '1' ? ['--no-sandbox'] : [],
});
let page;
try {
  page = await browser.newPage(); await page.setViewport({ width, height: 950, deviceScaleFactor: 1 });
  await page.setRequestInterception(true);
  page.on('request', request => {
    if (new URL(request.url()).origin === `http://127.0.0.1:${port}`) void request.continue();
    else void request.abort();
  });
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}/tasks`, { waitUntil: 'networkidle0' });
  async function click(text, scope = '') {
    const selector = `${scope} ::-p-text(${text})`.trim();
    const element = await page.waitForSelector(selector);
    await element.evaluate((node) => node.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }));
    await page.locator(selector).click();
  }
  async function waitText(text) { await page.waitForFunction(value => document.body.innerText.toLowerCase().replace(/\s+/gu, ' ').includes(value.toLowerCase()), {}, text); }
  await click('Open context'); await page.waitForSelector('textarea:not([disabled])');
  await page.type('textarea', 'Garage layout: reserve a workbench and bicycle access.');
  const upload = await page.$('input[type=file]'); await upload.uploadFile(process.env.MENTAT_CONTEXT_TEST_FILE);
  await waitText('File staged.'); await click('Publish context version'); await waitText('Saved a new context version.');
  await page.select('::-p-aria(Agent)', 'agent_research');
  await click('Review Agent access'); await waitText('Allow Research Agent to use version 1?');
  const preview = await page.$eval('[aria-label="Agent access preview"]', node => node.innerText);
  assert(preview.includes('dimensions.md') && preview.includes('reserve a workbench'));
  await click('Approve access'); await waitText('Agent access approved for the reviewed version.');
  await click('Research garage organization');
  await click('Prepare inputs'); await page.waitForSelector('section[aria-label="Task inputs"] input[type="checkbox"]');
  await page.click('section[aria-label="Task inputs"] input[type="checkbox"]');
  await page.type('section[aria-label="Task inputs"] textarea', 'Research organization options and preserve bicycle clearance.');
  await click('Save input version'); await waitText('Saved Task input version 1.');
  await click('Revoke access'); await waitText('Agent access revoked.');
  await click('Delete Task'); await waitText('Saved Task inputs (1 versions)');
  await click('Confirm delete Task'); await waitText('Deleted 0 Projects, 1 Task');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  assert.equal(overflow, false, 'context editor creates horizontal overflow');
  const output = resolve('../artifacts/project-context-editor'); await mkdir(output, { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(output, `${width}.png`), fullPage: true });
  if (width === 390) await click('Projects and saved views');
  await click('Retained Task inputs'); await waitText('Research organization options');
  await click('View retained input'); await click('Review input removal'); await waitText('This cannot be undone.');
  await click('Confirm input removal'); await waitText('No retained Task inputs.');
  await click('Retained Project history');
  const history = 'section[aria-label="Retained Project history"]';
  assert.equal(await page.$eval(`${history} button`, element => element.getAttribute('aria-expanded')), 'true');
  await waitText('Previous garage goals');
  await click('View saved version', history); await page.waitForSelector(`${history} h4`);
  await click('Review removal', history); await waitText('This cannot be undone.');
  await click('Confirm removal', history); await waitText('No retained history.');
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ width, publish: true, exactGrant: true, revoke: true, retiredPrune: true, overflow: false }));
} catch (error) {
  if (page) {
    console.error(await page.evaluate(() => ({ text: document.body.innerText.slice(-5000), selects: Array.from(document.querySelectorAll('select')).map(node => ({ label: node.parentElement.textContent, value: node.value })) })));
    const output = resolve('../artifacts/project-context-editor'); await mkdir(output, { recursive: true });
    await page.screenshot({ path: resolve(output, `${width}-failed.png`), fullPage: true });
  }
  throw error;
} finally { await browser.close(); }
