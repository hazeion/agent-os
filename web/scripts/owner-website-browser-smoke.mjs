// Hermetic browser acceptance: provider traffic is intercepted, never sent.
import http from 'node:http';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import puppeteer from 'puppeteer-core';

const port = Number(process.env.MENTAT_WEBSITE_TEST_PORT);
assert(Number.isInteger(port) && port > 0 && port < 65536);
const browser = await puppeteer.launch({executablePath: process.env.CHROME_PATH, headless: true});
let providerCase = 'owner-account';
const events = [];
async function device() {
  const context = await browser.createBrowserContext();
  const page = await context.newPage();
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      const url = new URL(request.url());
      if (url.origin === 'https://accounts.google.com') {
        const callback = new URL('https://mentat.example/auth/google/callback');
        callback.searchParams.set('state', url.searchParams.get('state'));
        if (providerCase === 'cancelled') callback.searchParams.set('error', 'access_denied');
        else callback.searchParams.set('code', providerCase);
        await request.respond({status: 303, headers: {location: callback.href}});
      } else if (url.origin === 'https://mentat.example') {
        const headers = {...request.headers(), host: 'mentat.example', 'x-forwarded-proto': 'https', 'x-forwarded-host': 'mentat.example'};
        headers['sec-fetch-mode'] = request.isNavigationRequest() ? 'navigate' : 'cors';
        headers['sec-fetch-dest'] = request.isNavigationRequest() ? 'document' : 'empty';
        headers['sec-fetch-site'] = request.redirectChain().some(item => new URL(item.url()).origin === 'https://accounts.google.com') ? 'cross-site' : 'same-origin';
        if (request.postData() !== undefined) headers['content-length'] = String(Buffer.byteLength(request.postData()));
        const response = await new Promise((resolve, reject) => {
          const outgoing = http.request({hostname: '127.0.0.1', port, method: request.method(), path: url.pathname + url.search, headers}, incoming => {
            const chunks = []; incoming.on('data', chunk => chunks.push(chunk));
            incoming.on('end', () => resolve({status: incoming.statusCode, headers: incoming.headers, body: Buffer.concat(chunks)}));
          });
          outgoing.on('error', reject); outgoing.end(request.postData());
        });
        if (url.pathname.startsWith('/auth/') || url.pathname === '/sign-in') events.push({path: url.pathname, method: request.method(), status: response.status, cookie: Boolean(headers.cookie), destination: response.headers.location ? new URL(response.headers.location, url).pathname : null, result: response.headers.location ? new URL(response.headers.location, url).searchParams.get('status') : null});
        await request.respond(response);
      } else await request.abort();
    } catch { await request.abort().catch(() => {}); }
  });
  return {context, page};
}
async function signIn(page, expected) {
  await page.waitForFunction(() => document.documentElement.dataset.shellHydrated === 'true');
  await page.waitForSelector('button[type=submit]:not([disabled])');
  await Promise.all([
    page.waitForFunction(target => target === 'owner' ? location.pathname === '/'
      : location.pathname === '/sign-in' && new URL(location.href).searchParams.get('status') === target, {}, expected),
    page.click('button[type=submit]'),
  ]);
}
try {
  const first = await device();
  await first.page.setViewport({width: 1280, height: 900});
  await first.page.goto('https://mentat.example/');
  assert.equal(new URL(first.page.url()).pathname, '/sign-in');
  assert.equal(await first.page.$eval('h1', element => element.textContent), 'Sign in to Mentat');
  const denied = await first.page.evaluate(async () => { const response = await fetch('/api/tasks'); return {status: response.status, body: await response.text()}; });
  assert.equal(denied.status, 401);
  assert(!denied.body.includes('Owner-only fixture task'));
  const output = process.env.MENTAT_WEBSITE_SCREENSHOT_ROOT;
  if (output) { await mkdir(output, {recursive: true}); await first.page.screenshot({path: join(output, 'desktop.png')}); }
  await first.page.setViewport({width: 390, height: 844});
  if (output) await first.page.screenshot({path: join(output, 'mobile.png')});
  assert(await first.page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  providerCase = 'wrong-account';
  await signIn(first.page, 'wrong_account');
  assert.equal(new URL(first.page.url()).pathname, '/sign-in');
  assert.equal(new URL(first.page.url()).searchParams.get('status'), 'wrong_account');
  assert(!(await first.context.cookies()).some(cookie => cookie.name === '__Host-mentat'));
  for (const [scenario, status] of [['cancelled', 'cancelled'], ['expired', 'expired'], ['provider-unavailable', 'unavailable']]) {
    providerCase = scenario;
    await signIn(first.page, status);
    assert(!(await first.context.cookies()).some(cookie => cookie.name === '__Host-mentat'));
  }
  providerCase = 'owner-account';
  await signIn(first.page, 'owner');
  assert.equal(new URL(first.page.url()).pathname, '/', JSON.stringify(events));
  const cookies = await first.context.cookies();
  const session = cookies.find(cookie => cookie.name === '__Host-mentat');
  assert(session?.secure && session.httpOnly && session.sameSite === 'Lax');
  assert(!await first.page.evaluate(() => document.cookie.includes('__Host-mentat=')));
  assert.equal(await first.page.evaluate(async () => (await fetch('/api/tasks')).status), 200);
  assert.equal(await first.page.evaluate(async () => (await fetch('/api/auth/sign-out', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'})).status), 401);
  const second = await device();
  await second.page.goto('https://mentat.example/sign-in');
  await signIn(second.page, 'owner');
  assert.equal(new URL(second.page.url()).pathname, '/', JSON.stringify(events));
  await first.page.waitForSelector('[data-owner-session]:not([hidden])');
  await first.page.click('[data-owner-session] summary');
  await Promise.all([first.page.waitForFunction(() => location.pathname === '/sign-in'), first.page.click('[data-owner-sign-out]')]);
  assert.equal(new URL(first.page.url()).pathname, '/sign-in');
  assert.equal(await first.page.evaluate(async () => (await fetch('/api/tasks')).status), 401);
  assert.equal(await second.page.evaluate(async () => (await fetch('/api/tasks')).status), 200);
  await signIn(first.page, 'owner');
  await second.page.waitForSelector('[data-owner-session]:not([hidden])');
  second.page.on('dialog', dialog => dialog.accept());
  await second.page.click('[data-owner-session] summary');
  await Promise.all([second.page.waitForFunction(() => location.pathname === '/sign-in'), second.page.click('[data-owner-sign-out-all]')]);
  assert.equal(await first.page.evaluate(async () => (await fetch('/api/tasks')).status), 401);
  await first.page.reload();
  assert.equal(new URL(first.page.url()).pathname, '/sign-in');
  process.stdout.write('Owner website browser checks passed\n');
} finally { await browser.close(); }
