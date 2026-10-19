// Standalone setup gateway: fixed presentation and two Python capabilities only.
import http from 'node:http';

const origin = process.env.MENTAT_SETUP_ORIGIN;
const bridge = process.env.MENTAT_SETUP_BRIDGE;
const token = process.env.MENTAT_SETUP_TOKEN;
const instance = process.env.MENTAT_SETUP_INSTANCE ?? '';
const port = Number(process.env.MENTAT_SETUP_PORT ?? '8888');
const canonical = new URL(origin);
if (canonical.protocol !== 'https:' || canonical.origin !== origin || canonical.port || !/^[a-z0-9.-]+$/.test(canonical.hostname)
    || !/^http:\/\/127\.0\.0\.1:[0-9]{1,5}$/.test(bridge ?? '') || !/^[A-Za-z0-9_-]{43}$/.test(token ?? '')
    || (instance && !/^[A-Za-z0-9_-]{43}$/.test(instance)) || !Number.isInteger(port) || port < 1 || port > 65535) process.exit(2);
const cookieName = '__Host-mentat-setup';
let inflight = 0;
let stopping = false;
const headers = {
  'cache-control': 'no-store', 'referrer-policy': 'no-referrer',
  'x-content-type-options': 'nosniff',
  'content-security-policy': "default-src 'none'; form-action 'self' https://accounts.google.com; base-uri 'none'; frame-ancestors 'none'",
};
const page = (title, content) => `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="mentat-setup-instance" content="${instance}"><title>${title}</title><main><h1>${title}</h1>${content}</main></html>`;
const setupPage = page('Connect your Mentat owner', '<p>Enter the setup code shown in your host terminal, then continue with Google.</p><form method="post" action="/auth/setup/start"><label>Setup code <input name="grant" required autocomplete="off" maxlength="43"></label><button type="submit">Continue with Google</button></form>');
const completePage = page('Return to your host terminal', '<p>If Google verification succeeded, your terminal will show the account for confirmation. Ownership changes only after you confirm there. If it did not succeed, cancel setup in the terminal and start again.</p>');
const failedPage = page('Setup could not continue', '<p>The code or sign-in attempt may have expired. Return to your host terminal and start a new setup ceremony.</p>');
function reply(res, status, body, extra = {}) {
  res.writeHead(status, {...headers, 'content-type': 'text/html; charset=utf-8', 'content-length': Buffer.byteLength(body), ...extra});
  res.end(body);
}
function oneHeader(req, name) {
  const values = [];
  for (let i = 0; i < req.rawHeaders.length; i += 2) if (req.rawHeaders[i].toLowerCase() === name) values.push(req.rawHeaders[i + 1]);
  if (values.length !== 1) throw new Error('invalid');
  return values[0];
}
function exactParams(params, names) {
  const entries = [...params.entries()];
  if (entries.length !== names.length || names.some(name => params.getAll(name).length !== 1) || entries.some(([key]) => !names.includes(key))) throw new Error('invalid');
  return Object.fromEntries(entries);
}
async function capability(path, body) {
  const raw = JSON.stringify(body);
  const response = await fetch(bridge + path, {method: 'POST', redirect: 'error', signal: AbortSignal.timeout(15000),
    headers: {'content-type': 'application/json', 'x-mentat-setup-token': token}, body: raw});
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 8192 || response.status !== 200) throw new Error('invalid');
  return JSON.parse(Buffer.from(bytes).toString('utf8'));
}
const server = http.createServer({maxHeaderSize: 16384, requestTimeout: 10000, headersTimeout: 5000}, async (req, res) => {
  if (stopping || inflight >= 2) return reply(res, 503, failedPage);
  inflight++;
  try {
    if (oneHeader(req, 'host') !== canonical.host || oneHeader(req, 'x-forwarded-proto') !== 'https'
        || oneHeader(req, 'x-forwarded-host') !== canonical.host || req.headers.forwarded || req.headers['x-real-ip']
        || req.headers['x-forwarded-for'] || req.headers['x-forwarded-port'] || !req.url.startsWith('/') || req.url.length > 16384) throw new Error('invalid');
    const url = new URL(req.url, origin);
    if (url.origin !== origin || url.hash || req.url.split('?')[0] !== url.pathname) throw new Error('invalid');
    if (req.method === 'GET' && !url.search && url.pathname === '/auth/setup') return reply(res, 200, setupPage, {'referrer-policy': 'same-origin'});
    if (req.method === 'GET' && !url.search && url.pathname === '/auth/setup/complete') return reply(res, 200, completePage);
    if (req.method === 'POST' && url.pathname === '/auth/setup/start' && !url.search) {
      if (oneHeader(req, 'origin') !== origin || oneHeader(req, 'content-type') !== 'application/x-www-form-urlencoded'
          || req.headers['transfer-encoding'] || (req.headers['sec-fetch-site'] && req.headers['sec-fetch-site'] !== 'same-origin')) throw new Error('invalid');
      const length = oneHeader(req, 'content-length');
      if (!/^[0-9]{1,4}$/.test(length) || Number(length) > 8192) throw new Error('invalid');
      const chunks = []; let size = 0;
      for await (const chunk of req) { size += chunk.length; if (size > 8192) throw new Error('invalid'); chunks.push(chunk); }
      if (size !== Number(length)) throw new Error('invalid');
      const body = exactParams(new URLSearchParams(Buffer.concat(chunks).toString('utf8')), ['grant']);
      if (!/^[A-Za-z0-9_-]{43}$/.test(body.grant)) throw new Error('invalid');
      const result = await capability('/setup/begin', body);
      if (Object.keys(result).sort().join() !== 'authorization_url,browser_binding,ok' || result.ok !== true || !/^[A-Za-z0-9_-]{43}$/.test(result.browser_binding)) throw new Error('invalid');
      const authorization = new URL(result.authorization_url);
      if (authorization.origin !== 'https://accounts.google.com' || authorization.pathname !== '/o/oauth2/v2/auth' || result.authorization_url.length > 4096) throw new Error('invalid');
      return reply(res, 303, '', {'location': result.authorization_url, 'set-cookie': `${cookieName}=${result.browser_binding}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=600`});
    }
    if (req.method === 'GET' && url.pathname === '/auth/google/callback') {
      try {
        const names = ['state', 'code', 'scope', 'authuser', 'prompt'];
        if ([...url.searchParams].some(([key, value]) => !names.includes(key) || url.searchParams.getAll(key).length !== 1 || value.length > 4096)) throw new Error('invalid');
        const body = {state: url.searchParams.get('state'), code: url.searchParams.get('code')};
        if (!/^[A-Za-z0-9_-]{43}$/.test(body.state ?? '') || typeof body.code !== 'string' || body.code.length < 1 || body.code.length > 4096) throw new Error('invalid');
        const cookies = oneHeader(req, 'cookie').split(';').map(value => value.trim()).filter(value => value.startsWith(cookieName + '='));
        if (cookies.length !== 1 || !/^[A-Za-z0-9_-]{43}$/.test(cookies[0].slice(cookieName.length + 1))) throw new Error('invalid');
        const result = await capability('/setup/callback', {...body, browser_binding: cookies[0].slice(cookieName.length + 1)});
        if (Object.keys(result).join() !== 'ok' || result.ok !== true) throw new Error('invalid');
      } catch { /* Always remove callback query and cookie; never reflect provider text. */ }
      return reply(res, 303, '', {'location': '/auth/setup/complete', 'set-cookie': `${cookieName}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0`});
    }
    return reply(res, 404, failedPage);
  } catch {
    return reply(res, 403, failedPage);
  } finally { inflight--; }
});
server.maxConnections = 8;
server.keepAliveTimeout = 1000;
server.on('clientError', (_error, socket) => socket.destroy());
server.on('error', () => process.exit(2));
server.listen(port, '127.0.0.1', () => process.stdout.write('ready\n'));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => {
  stopping = true;
  server.close(() => process.exit(0));
  setTimeout(() => { server.closeAllConnections(); process.exit(2); }, 17000).unref();
});
