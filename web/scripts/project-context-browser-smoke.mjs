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
  await page.goto(`http://127.0.0.1:${port}/tasks`, { waitUntil: 'domcontentloaded' });
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
  await click('Open plan'); await click('Create plan');
  await page.type('section[aria-label="Project plan"] input[maxlength="120"]', 'Garage organization');
  await click('Add Research garage organization', 'section[aria-label="Project plan"]');
  await waitText('Current Task inputs match this plan.');
  await click('Review Task dependencies'); await waitText('Plan and canonical Task prerequisites match.');
  await click('Save plan version'); await waitText('Plan version saved. It remains unapproved and cannot start Agent work.');
  await click('Revoke access'); await waitText('Agent access revoked.');
  await click('Delete Task'); await waitText('Saved Task inputs (1 versions)'); await waitText('Saved Project plans (1 versions)');
  await click('Confirm delete Task'); await waitText('Deleted 0 Projects, 1 Task');
  await click('Open results'); await click('Create result');
  await page.type('section[aria-label="Project results"] input[type="number"]', '6000');
  const measurements = await page.$$('section[aria-label="Project results"] input[type="number"]');
  await measurements[1].type('5000');
  await click('Add object'); await page.type('section[aria-label="Project results"] .project-deliverable-row input', 'Workbench');
  await click('Save result version'); await waitText('Garage layout saved as a new version.');
  await page.waitForFunction(() => { const image = document.querySelector('img[alt="Saved dimensioned garage layout"]'); return image && image.complete && image.naturalWidth === 1200; });
  await click('Products and sources', 'section[aria-label="Project results"]'); await click('Create result');
  await click('Add product'); await page.type('section[aria-label="Project results"] .project-deliverable-row input', 'Wall shelf');
  await page.type('section[aria-label="Project results"] input[type="url"]', 'https://example.com/shelf');
  await click('Save result version'); await waitText('Products and sources saved as a new version.');
  await click('Download product document');
  await click('Implementation order', 'section[aria-label="Project results"]'); await click('Create result');
  await click('Add step'); await page.type('section[aria-label="Project results"] .project-deliverable-row input', 'Measure the walls');
  await click('Save result version'); await waitText('Implementation order saved as a new version.');
  await click('Download implementation document');
  await waitText('The current results need your review.');
  await click('Accept saved results'); await click('Preview acceptance');
  await waitText('Accept these exact saved versions?');
  assert.equal(await page.$$eval('[aria-label="Confirm Project result review"] section[aria-label$="current review version"]', nodes => nodes.length), 3);
  const reviewed = await page.$eval('[aria-label="Confirm Project result review"]', node => node.innerText);
  assert(reviewed.includes('Workbench') && reviewed.includes('Wall shelf') && reviewed.includes('Measure the walls'));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'review confirmation creates horizontal overflow');
  await click('Confirm acceptance'); await waitText('Acceptance recorded.');
  await click('Request changes', 'section[aria-label="Review Project results"]');
  const reviewSlots = await page.$$('section[aria-label="Review Project results"] input[type="checkbox"]');
  await reviewSlots[1].click();
  await page.type('section[aria-label="Review Project results"] textarea', 'Confirm shelf capacity before buying.');
  await click('Preview change request'); await waitText('Request changes to these exact saved versions?');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'change request creates horizontal overflow');
  await click('Send change request'); await waitText('Change request recorded.');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  assert.equal(overflow, false, 'context editor creates horizontal overflow');
  const output = resolve('../artifacts/project-context-editor'); await mkdir(output, { recursive: true });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: resolve(output, `${width}.png`), fullPage: true });
  if (width === 390) await click('Projects and saved views');
  await click('Retained Task inputs'); await waitText('Research organization options');
  await click('View retained input'); await click('Review input removal');
  await waitText('A saved Project plan still references this input version. Keep it in history.');
  await click('Retained Project history');
  const history = 'section[aria-label="Retained Project history"]';
  assert.equal(await page.$eval(`${history} button`, element => element.getAttribute('aria-expanded')), 'true');
  await waitText('Previous garage goals');
  await click('View saved version', history); await page.waitForSelector(`${history} h4`);
  await click('Review removal', history); await waitText('This cannot be undone.');
  await click('Confirm removal', history); await waitText('No retained history.');
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ width, publish: true, exactGrant: true, revoke: true, retainedPlanInputs: true, garageResults: true, ownerReview: true, ownerPlan: true, overflow: false }));
} catch (error) {
  if (page) {
    console.error(await page.evaluate(() => ({ text: document.body.innerText.slice(-5000), selects: Array.from(document.querySelectorAll('select')).map(node => ({ label: node.parentElement.textContent, value: node.value })) })));
    const output = resolve('../artifacts/project-context-editor'); await mkdir(output, { recursive: true });
    await page.screenshot({ path: resolve(output, `${width}-failed.png`), fullPage: true });
  }
  throw error;
} finally { await browser.close(); }
