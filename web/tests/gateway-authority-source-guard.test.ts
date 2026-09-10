import assert from "node:assert/strict";
import { readdir, readFile, stat } from "node:fs/promises";
import { dirname, extname, join, relative, resolve, sep } from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const WEB_ROOT = fileURLToPath(new URL("../", import.meta.url));
const SOURCE_ROOT = join(WEB_ROOT, "src");
const API_ROOT = join(SOURCE_ROOT, "app", "api");
const LIB_ROOT = join(SOURCE_ROOT, "lib");
const REQUEST_CONTEXT = join(LIB_ROOT, "gateway-request-context.ts");
const IMPLEMENTATION_WHITELIST = new Set([
  join(LIB_ROOT, "gateway-authority.ts"),
  REQUEST_CONTEXT,
  join(SOURCE_ROOT, "proxy.ts"),
]);
const HTTP_METHODS = new Set(["GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "DELETE"]);

/**
 * Every entry here is a deliberately reviewed route-factory module.  A route
 * may delegate to one of these factories only after this test proves its
 * implementation reaches the shared gateway wrapper.
 */
const APPROVED_WRAPPER_BACKED_ROUTE_FACTORIES = new Set([
  "@/lib/agent-attachments-route",
  "@/lib/agent-configuration-route",
  "@/lib/agent-setup-route",
  "@/lib/agent-task-creation-route",
  "@/lib/codex-readiness-route",
  "@/lib/command-manifest-route",
  "@/lib/conversation-archive-route",
  "@/lib/conversation-history-route",
  "@/lib/conversation-media-route",
  "@/lib/conversation-planning-context-route",
  "@/lib/conversation-queue-route",
  "@/lib/conversation-rename-route",
  "@/lib/conversation-retry-route",
  "@/lib/conversation-steer-route",
  "@/lib/conversation-turn-route",
  "@/lib/link-preview-route",
  "@/lib/planning-deletion-route",
  "@/lib/planning-dependency-map-route",
  "@/lib/planning-dependency-picker-route",
  "@/lib/planning-mutation-route",
  "@/lib/planning-overview-route",
  "@/lib/planning-search-route",
  "@/lib/planning-task-delegation-actions-route",
  "@/lib/planning-task-delegation-route",
  "@/lib/planning-task-dependencies-route",
  "@/lib/planning-task-detail-route",
  "@/lib/planning-task-execution-route",
  "@/lib/planning-task-integrations-route",
  "@/lib/planning-task-route",
  "@/lib/planning-tasks-route",
  "@/lib/project-creation-route",
]);

type ImportBinding = Readonly<{ local: string; module: string }>;

async function filesBelow(directory: string, predicate: (file: string) => boolean): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const file = join(directory, entry.name);
    if (entry.isDirectory()) return filesBelow(file, predicate);
    return predicate(file) ? [file] : [];
  }));
  return nested.flat();
}

async function readSource(file: string): Promise<ts.SourceFile> {
  return ts.createSourceFile(file, await readFile(file, "utf8"), ts.ScriptTarget.Latest, true);
}

function moduleText(node: ts.ImportDeclaration): string | null {
  return ts.isStringLiteral(node.moduleSpecifier) ? node.moduleSpecifier.text : null;
}

function importBindings(source: ts.SourceFile): ImportBinding[] {
  const bindings: ImportBinding[] = [];
  for (const statement of source.statements) {
    if (!ts.isImportDeclaration(statement)) continue;
    const modulePath = moduleText(statement);
    const clause = statement.importClause;
    if (!modulePath || !clause) continue;
    if (clause.name) bindings.push({ local: clause.name.text, module: modulePath });
    const named = clause.namedBindings;
    if (named && ts.isNamespaceImport(named)) bindings.push({ local: named.name.text, module: modulePath });
    if (named && ts.isNamedImports(named)) {
      for (const item of named.elements) bindings.push({ local: item.name.text, module: modulePath });
    }
  }
  return bindings;
}

function visitCode(node: ts.Node, visitor: (node: ts.Node) => void): void {
  if (ts.isImportDeclaration(node)) return;
  visitor(node);
  ts.forEachChild(node, (child) => visitCode(child, visitor));
}

function calls(source: ts.Node, name: string): boolean {
  let found = false;
  visitCode(source, (node) => {
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === name) found = true;
  });
  return found;
}

function pathUsesIdentifier(node: ts.Node, names: ReadonlySet<string>): boolean {
  let found = false;
  visitCode(node, (child) => {
    if (ts.isIdentifier(child) && names.has(child.text)) found = true;
  });
  return found;
}

function absolute(file: string): string {
  return resolve(file).split(sep).join("/");
}

async function existingFile(file: string): Promise<string | null> {
  try {
    return (await stat(file)).isFile() ? file : null;
  } catch {
    return null;
  }
}

async function resolveImport(from: string, specifier: string): Promise<string | null> {
  let base: string | null = null;
  if (specifier.startsWith("@/")) base = join(SOURCE_ROOT, specifier.slice(2));
  if (specifier.startsWith(".")) base = resolve(dirname(from), specifier);
  if (!base) return null;
  const candidates = extname(base) ? [base] : [`${base}.ts`, `${base}.tsx`, join(base, "index.ts")];
  for (const candidate of candidates) {
    const file = await existingFile(candidate);
    if (file) return file;
  }
  return null;
}

async function wrapperBacked(file: string, cache = new Map<string, Promise<boolean>>(), ancestors = new Set<string>()): Promise<boolean> {
  const normalized = absolute(file);
  if (normalized === absolute(REQUEST_CONTEXT)) return true;
  const cached = cache.get(normalized);
  if (cached) return cached;
  if (ancestors.has(normalized)) return false;
  const nextAncestors = new Set(ancestors);
  nextAncestors.add(normalized);
  const result = (async () => {
    const source = await readSource(file);
    for (const binding of importBindings(source)) {
      if (!calls(source, binding.local)) continue;
      const target = await resolveImport(file, binding.module);
      if (target && await wrapperBacked(target, cache, nextAncestors)) return true;
    }
    return false;
  })();
  cache.set(normalized, result);
  return result;
}

function httpExportImplementations(source: ts.SourceFile): Map<string, ts.Node> {
  const exports = new Map<string, ts.Node>();
  for (const statement of source.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.body
      && statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)
      && HTTP_METHODS.has(statement.name.text)) {
      exports.set(statement.name.text, statement.body);
    }
    if (!ts.isVariableStatement(statement) || !statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (ts.isIdentifier(declaration.name) && HTTP_METHODS.has(declaration.name.text) && declaration.initializer) {
        exports.set(declaration.name.text, declaration.initializer);
      }
    }
  }
  return exports;
}

function protectedLocalBindings(source: ts.SourceFile, directWrapper: string | null, factories: ReadonlySet<string>): Set<string> {
  const protectedNames = new Set<string>();
  for (const statement of source.statements) {
    if (!ts.isVariableStatement(statement)) continue;
    for (const declaration of statement.declarationList.declarations) {
      if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue;
      if (directWrapper && calls(declaration.initializer, directWrapper) || pathUsesIdentifier(declaration.initializer, factories)) {
        protectedNames.add(declaration.name.text);
      }
    }
  }
  return protectedNames;
}

function wrapperBackedLocalFactories(source: ts.SourceFile, directWrapper: string | null, importedFactories: ReadonlySet<string>): Set<string> {
  const factories = new Set(importedFactories);
  for (const statement of source.statements) {
    if (!ts.isFunctionDeclaration(statement) || !statement.name || !statement.body) continue;
    if (directWrapper && calls(statement.body, directWrapper) || pathUsesIdentifier(statement.body, importedFactories)) {
      factories.add(statement.name.text);
    }
  }
  return factories;
}

test("gateway authority has no legacy boundary path or unauthorized direct call site", async () => {
  const sourceFiles = await filesBelow(SOURCE_ROOT, (file) => /\.(?:ts|tsx)$/u.test(file));
  const violations: string[] = [];
  for (const file of sourceFiles) {
    const sourcePath = relative(WEB_ROOT, file).split(sep).join("/");
    assert.equal(sourcePath.includes("request-boundary"), false, `legacy request-boundary path remains: ${sourcePath}`);
    const source = await readSource(file);
    for (const binding of importBindings(source)) {
      assert.equal(binding.module.includes("request-boundary"), false, `legacy request-boundary import remains in ${sourcePath}`);
    }
    if (IMPLEMENTATION_WHITELIST.has(file)) continue;
    visitCode(source, (node) => {
      if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "evaluateGatewayAuthority") {
        violations.push(`${sourcePath}: evaluateGatewayAuthority`);
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
        && ts.isIdentifier(node.expression.expression) && node.expression.expression.text === "PROCESS_GATEWAY_AUTHORITY"
        && node.expression.name.text === "authorize") {
        violations.push(`${sourcePath}: PROCESS_GATEWAY_AUTHORITY.authorize`);
      }
    });
  }
  assert.deepEqual(violations, []);
});

test("every App Router API operation is directly wrapped or delegates to a reviewed wrapper-backed factory", async () => {
  const approvedFactories = new Map<string, string>();
  for (const modulePath of APPROVED_WRAPPER_BACKED_ROUTE_FACTORIES) {
    const file = await resolveImport(REQUEST_CONTEXT, modulePath);
    assert.ok(file, `approved factory must resolve: ${modulePath}`);
    assert.equal(await wrapperBacked(file), true, `approved factory must invoke the shared wrapper: ${modulePath}`);
    approvedFactories.set(modulePath, file);
  }

  const routeFiles = await filesBelow(API_ROOT, (file) => file.endsWith(`${sep}route.ts`));
  assert.ok(routeFiles.length > 0);
  for (const file of routeFiles) {
    const source = await readSource(file);
    const bindings = importBindings(source);
    const directWrapper = bindings.find((binding) => binding.module === "@/lib/gateway-request-context" && binding.local === "withGatewayRoute")?.local ?? null;
    const factoryBindings = new Set(bindings.filter((binding) => approvedFactories.has(binding.module)).map((binding) => binding.local));
    const localFactories = wrapperBackedLocalFactories(source, directWrapper, factoryBindings);
    const protectedNames = protectedLocalBindings(source, directWrapper, localFactories);
    const operations = httpExportImplementations(source);
    const routePath = relative(WEB_ROOT, file).split(sep).join("/");
    assert.ok(operations.size > 0, `route has no exported HTTP operation: ${routePath}`);
    for (const [method, initializer] of operations) {
      const directlyWrapped = directWrapper !== null && calls(initializer, directWrapper) || pathUsesIdentifier(initializer, protectedNames);
      const delegated = pathUsesIdentifier(initializer, factoryBindings);
      assert.equal(directlyWrapped || delegated, true, `${routePath} ${method} bypasses withGatewayRoute or an approved wrapper-backed factory`);
    }
  }
});

function concreteRoute(path: string): { params: Record<string, string | string[]>; pathname: string } {
  const params: Record<string, string | string[]> = {};
  const pathname = path
    .replace(/\[\[\.\.\.([^\]]+)\]\]/gu, (_match, name: string) => { params[name] = ["test"]; return "test"; })
    .replace(/\[\.\.\.([^\]]+)\]/gu, (_match, name: string) => { params[name] = ["test"]; return "test"; })
    .replace(/\[([^\]]+)\]/gu, (_match, name: string) => { params[name] = "test"; return "test"; });
  return { params, pathname };
}

test("every exported API operation admits its own manifest method and path before route validation", async () => {
  const routeFiles = await filesBelow(API_ROOT, (file) => file.endsWith(`${sep}route.ts`));
  const originalFetch = globalThis.fetch;
  let transportCalls = 0;
  globalThis.fetch = (async () => {
    transportCalls += 1;
    throw new Error("gateway source guard reached transport");
  }) as typeof fetch;
  try {
    for (const file of routeFiles) {
      const source = await readSource(file);
      const operations = httpExportImplementations(source);
      const sourcePath = relative(WEB_ROOT, file).split(sep).join("/");
      const template = `/api/${relative(API_ROOT, file).split(sep).join("/").replace(/\/route\.ts$/u, "")}`;
      const { params, pathname } = concreteRoute(template);
      const routeModule = await import(`${pathToFileURL(file).href}?gateway-source-guard=${encodeURIComponent(template)}`) as Record<string, unknown>;
      for (const method of operations.keys()) {
        const operation = routeModule[method];
        assert.equal(typeof operation, "function", `${sourcePath} must export ${method}`);
        const safe = new Set(["GET", "HEAD", "OPTIONS"]).has(method);
        const request = new Request(`http://127.0.0.1:3000${pathname}${safe ? "?__gateway_source_guard=1" : ""}`, {
          body: safe ? undefined : "[",
          headers: {
            Host: "127.0.0.1:3000",
            Origin: "http://127.0.0.1:3000",
            "Sec-Fetch-Site": "same-origin",
            ...(safe ? {} : { "Content-Type": "application/json" }),
          },
          method,
        });
        const before = transportCalls;
        const response = await (operation as (request: Request, context: { params: Promise<Record<string, string | string[]>> }) => Promise<Response>)(request, { params: Promise.resolve(params) });
        assert.ok(response instanceof Response, `${sourcePath} ${method} must return a Response`);
        const expectedStatus = template === "/api/link-previews/images/[imageId]" ? 404 : 400;
        assert.equal(response.status, expectedStatus, `${sourcePath} ${method} must reject its sentinel during route validation`);
        assert.equal(transportCalls, before, `${sourcePath} ${method} reached transport before rejecting its sentinel`);
      }
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});
