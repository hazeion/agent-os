import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join, relative, sep } from "node:path";
import test from "node:test";

import { GATEWAY_ROUTE_MANIFEST, type GatewayHttpMethod } from "../src/lib/gateway-route-manifest.ts";

const API_ROOT = fileURLToPath(new URL("../src/app/api/", import.meta.url));
const APP_ROOT = fileURLToPath(new URL("../src/app/", import.meta.url));
const PUBLIC_ROOT = fileURLToPath(new URL("../public/", import.meta.url));
const NEXT_CONFIG = fileURLToPath(new URL("../next.config.ts", import.meta.url));
const STANDALONE_PREPARER = fileURLToPath(new URL("../scripts/prepare-standalone.mjs", import.meta.url));
const METHOD_EXPORT = /export\s+(?:(?:async\s+)?function\s+|(const|let|var)\s+)(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*(?:\(|=)/gu;

async function routeFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => entry.isDirectory() ? routeFiles(join(directory, entry.name)) : entry.name === "route.ts" ? [join(directory, entry.name)] : []));
  return nested.flat();
}

async function namedFiles(directory: string, filename: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => entry.isDirectory() ? namedFiles(join(directory, entry.name), filename) : entry.name === filename ? [join(directory, entry.name)] : []));
  return nested.flat();
}

async function publicFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => entry.isDirectory() ? publicFiles(join(directory, entry.name)) : entry.isFile() ? [join(directory, entry.name)] : []));
  return nested.flat();
}

function operationKey(method: string, path: string): string {
  return `${method} ${path}`;
}

test("the immutable manifest has one complete, non-duplicated rule per current API operation", async () => {
  assert.ok(Object.isFrozen(GATEWAY_ROUTE_MANIFEST));
  const sourceOperations = new Map<string, string>();
  const files = await routeFiles(API_ROOT);
  assert.equal(files.length, 87);
  for (const file of files) {
    const source = `web/src/app/api/${relative(API_ROOT, file).split(sep).join("/")}`;
    const path = `/api/${relative(API_ROOT, file).split(sep).join("/").replace(/\/route\.ts$/u, "")}`;
    const content = await readFile(file, "utf8");
    for (const match of content.matchAll(METHOD_EXPORT)) {
      const method = match[2] as GatewayHttpMethod;
      const key = operationKey(method, path);
      assert.equal(sourceOperations.has(key), false, `duplicate source operation ${key}`);
      sourceOperations.set(key, source);
    }
  }

  const manifestOperations = new Map<string, string>();
  for (const row of GATEWAY_ROUTE_MANIFEST.filter((candidate) => candidate.path.startsWith("/api/"))) {
    assert.ok(Object.isFrozen(row));
    const key = operationKey(row.method, row.path);
    assert.equal(manifestOperations.has(key), false, `duplicate manifest operation ${key}`);
    manifestOperations.set(key, row.source);
    assert.equal(row.validator, `route:${row.source.slice("web/src/app/api/".length, -"/route.ts".length)}#${row.method}`);
    assert.equal(row.csrf, ["GET", "HEAD", "OPTIONS"].includes(row.method) ? "not_required" : "session_bound");
    assert.equal(row.idempotency, ["GET", "HEAD", "OPTIONS"].includes(row.method) ? "not_applicable" : "route_owned");
    assert.equal(row.budget, row.path.endsWith("/events") ? "gateway_stream" : ["GET", "HEAD", "OPTIONS"].includes(row.method) ? "gateway_read" : "gateway_mutation");
    assert.equal(row.projection, "route_owned");
    assert.equal(row.audit, ["GET", "HEAD", "OPTIONS"].includes(row.method) ? "gateway_api_read" : "gateway_api_mutation");
    const supervisor = row.path === "/api/bridge/health" || row.path === "/api/gateway/health";
    assert.equal(row.exposure, supervisor ? "local_only" : "owner_session");
    assert.equal(row.bridgeCapability, supervisor ? null : `bridge:${row.path.slice("/api/".length).replaceAll("/", ".")}.${row.method.toLowerCase()}`);
  }

  assert.deepEqual([...manifestOperations.keys()].sort(), [...sourceOperations.keys()].sort());
  for (const [key, source] of sourceOperations) assert.equal(manifestOperations.get(key), source, key);
  assert.equal(sourceOperations.size, 94);
  assert.equal(GATEWAY_ROUTE_MANIFEST.filter((candidate) => candidate.path.startsWith("/api/")).length, 94);
});

test("the static manifest is source-derived, finite, and includes only shipped dashboard surfaces", async () => {
  const staticRows = GATEWAY_ROUTE_MANIFEST.filter((row) => row.exposure === "static");
  const rowsByPath = new Map<string, typeof staticRows>();
  for (const row of staticRows) {
    assert.ok(Object.isFrozen(row));
    assert.equal(row.audit, "gateway_static_read");
    assert.equal(row.bridgeCapability, null);
    assert.equal(row.budget, "gateway_read");
    assert.equal(row.csrf, "not_required");
    assert.equal(row.idempotency, "not_applicable");
    assert.equal(row.projection, "static");
    assert.equal(row.validator, `static:${row.path}`);
    rowsByPath.set(row.path, [...(rowsByPath.get(row.path) ?? []), row]);
  }

  const authoredDocuments = (await namedFiles(APP_ROOT, "page.tsx")).map((file) => {
    const directory = relative(APP_ROOT, file).split(sep).slice(0, -1).join("/");
    const path = directory ? `/${directory}` : "/";
    return [path, `web/src/app/${directory ? `${directory}/` : ""}page.tsx`] as const;
  });
  const publicAssets = (await publicFiles(PUBLIC_ROOT)).map((file) => {
    const asset = relative(PUBLIC_ROOT, file).split(sep).join("/");
    return [`/${asset}`, `web/public/${asset}`] as const;
  });
  const config = await readFile(NEXT_CONFIG, "utf8");
  const generatedShells = [...config.matchAll(/destination:\s*"(\/shell\/[^"/]+\.html)"/gu)].map((match) => match[1]!);
  const preparer = await readFile(STANDALONE_PREPARER, "utf8");
  const generatedOutputs = [...preparer.matchAll(/output:\s*"([^"/]+\.html)"/gu)].map((match) => `/shell/${match[1]!}`);
  assert.deepEqual(generatedShells.sort(), generatedOutputs.sort(), "rewrites and generated shell outputs drifted");

  const expected = new Map<string, string>([
    ...authoredDocuments,
    ["/icon.svg", "web/src/app/icon.svg"],
    ...publicAssets,
    ...generatedShells.map((path) => [path, "web/scripts/prepare-standalone.mjs"] as const),
    ["/_next/static/[...path]", "framework:next"],
  ]);
  assert.deepEqual([...rowsByPath.keys()].sort(), [...expected.keys()].sort());
  for (const [path, source] of expected) {
    const rows = rowsByPath.get(path);
    assert.ok(rows, `missing static route ${path}`);
    assert.deepEqual(rows.map((row) => row.method).sort(), ["GET", "HEAD"]);
    assert.deepEqual(new Set(rows.map((row) => row.source)), new Set([source]));
  }
  assert.equal(rowsByPath.has("/favicon.ico"), false);
});
