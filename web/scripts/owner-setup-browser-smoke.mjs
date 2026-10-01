// Hermetic Chromium CSP regression. Google requests are intercepted, never sent.
import http from 'node:http';
import assert from 'node:assert/strict';
import puppeteer from 'puppeteer-core';

const port = Number(process.env.MENTAT_SETUP_TEST_PORT);
const grant = process.env.MENTAT_SETUP_TEST_GRANT;
const blockingControl = process.env.MENTAT_SETUP_TEST_BLOCK === '1';
assert(Number.isInteger(port) && port > 0 && port < 65536);
assert(/^[A-Za-z0-9_-]{43}$/.test(grant ?? ''));
const browser = await puppeteer.launch({executablePath: process.env.CHROME_PATH, headless: true});
try {
  const page = await browser.newPage();
  let googleReached = false;
  let cspBlocked = false;
  const events = [];
  page.on('console', message => { if (message.text().includes('form-action')) cspBlocked = true; });
  await page.setRequestInterception(true);
  page.on('request', async request => {
    try {
      const url = new URL(request.url());
      if (url.origin === 'https://accounts.google.com') {
        googleReached = true;
        await request.respond({status: 200, contentType: 'text/html', body: '<title>Intercepted Google authorization</title>'});
      } else if (url.origin === 'https://mentat.example') {
        const headers = {...request.headers(), host: 'mentat.example', 'x-forwarded-proto': 'https', 'x-forwarded-host': 'mentat.example'};
        if (request.postData() !== undefined) headers['content-length'] = String(Buffer.byteLength(request.postData()));
        const upstream = await new Promise((resolve, reject) => {
          const outgoing = http.request({hostname: '127.0.0.1', port, method: request.method(), path: url.pathname + url.search, headers}, response => {
            const chunks = [];
            response.on('data', chunk => chunks.push(chunk));
            response.on('end', () => resolve({status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks)}));
          });
          outgoing.on('error', reject);
          outgoing.end(request.postData());
        });
        if (blockingControl) upstream.headers['content-security-policy'] = "default-src 'none'; form-action 'self'";
        events.push({method: request.method(), path: url.pathname, status: upstream.status,
          origin: headers.origin, type: headers['content-type'], site: headers['sec-fetch-site'],
          length: headers['content-length'], actualLength: request.postData()?.length,
          formKeys: request.postData() ? [...new URLSearchParams(request.postData()).keys()] : []});
        await request.respond(upstream);
      } else await request.abort();
    } catch { await request.abort().catch(() => {}); }
  });
  await page.goto('https://mentat.example/auth/setup');
  await page.type('input[name=grant]', grant);
  await page.click('button');
  const deadline = Date.now() + 10000;
  while (!googleReached && !cspBlocked && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 50));
  assert(blockingControl ? cspBlocked && !googleReached : googleReached && !cspBlocked, JSON.stringify({googleReached, cspBlocked, events}));
  process.stdout.write(blockingControl ? 'Restrictive CSP control blocked Google redirect\n' : 'Browser followed the permitted Google redirect\n');
} finally { await browser.close(); }
