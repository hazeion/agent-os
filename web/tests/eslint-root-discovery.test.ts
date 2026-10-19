import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join, parse, resolve } from "node:path";
import test from "node:test";
import { Linter } from "eslint";

const require = createRequire(import.meta.url);
const { getRootDirs } = require("@next/eslint-plugin-next/dist/utils/get-root-dirs.js") as {
  getRootDirs(context: { cwd: string; settings: { next?: { rootDir: string | string[] } } }): string[];
};

test("Next lint discovers directory roots through the scoped glob replacement", () => {
  const root = mkdtempSync(join(tmpdir(), "mentat-lint-roots-"));
  // Next consumes these as filesystem paths. Compare their resolved targets,
  // allowing the replacement's relative directory paths and trailing slash.
  const normalized = (path: string) => resolve(path).replace(/\\/g, "/");
  try {
    for (const directory of ["apps/web/nested", "apps/docs/nested", "packages/ui/nested"]) {
      mkdirSync(join(root, directory), { recursive: true });
    }
    writeFileSync(join(root, "apps/readme.md"), "Not an application directory");
    assert.deepEqual(getRootDirs({ cwd: root, settings: {} }), [root]);
    const filesystemRoot = parse(root).root;
    assert.deepEqual(
      getRootDirs({ cwd: root, settings: { next: { rootDir: filesystemRoot } } }).map(normalized),
      [normalized(filesystemRoot)],
    );
    assert.deepEqual(
      getRootDirs({ cwd: root, settings: { next: { rootDir: join(root, "apps/web") } } }).map(normalized),
      [normalized(join(root, "apps/web"))],
    );
    assert.deepEqual(
      getRootDirs({ cwd: root, settings: { next: { rootDir: join(root, "apps/*") } } }).map(normalized).sort(),
      [join(root, "apps/docs"), join(root, "apps/web")].map(normalized).sort(),
    );
    assert.deepEqual(
      getRootDirs({ cwd: root, settings: { next: {
        rootDir: [join(root, "apps/{web,docs}"), join(root, "packages/*")],
      } } }).map(normalized).sort(),
      [join(root, "apps/docs"), join(root, "apps/web"), join(root, "packages/ui")].map(normalized).sort(),
    );
    assert.deepEqual(
      getRootDirs({ cwd: root, settings: { next: { rootDir: join(root, "missing/*") } } }),
      [],
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Next lint still rejects plain anchors to pages discovered through root globs", () => {
  const root = mkdtempSync(join(tmpdir(), "mentat-lint-pages-"));
  try {
    for (const [app, page] of [["web", "about"], ["docs", "contact"]]) {
      const pages = join(root, "apps", app, "pages");
      mkdirSync(pages, { recursive: true });
      writeFileSync(join(pages, `${page}.tsx`), "export default function Page() { return null; }");
    }
    const unrelatedPages = join(root, "apps/web/fixtures/other/pages");
    mkdirSync(unrelatedPages, { recursive: true });
    writeFileSync(join(unrelatedPages, "unrelated.tsx"), "export default function Page() { return null; }");
    const plugin = require("@next/eslint-plugin-next");
    const linter = new Linter();
    const config = [{
      files: ["**/*.jsx"],
      languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } },
      plugins: { "@next/next": plugin },
      settings: { next: { rootDir: join(root, "apps/{web,docs}") } },
      rules: { "@next/next/no-html-link-for-pages": "error" as const },
    }];
    for (const page of ["about", "contact"]) {
      const messages = linter.verify(`const page = <a href="/${page}">Page</a>;`, config, "fixture.jsx");
      assert.equal(messages.length, 1);
      assert.equal(messages[0].ruleId, "@next/next/no-html-link-for-pages");
      assert.match(messages[0].message, /Do not use an.*element to navigate/);
    }
    assert.deepEqual(
      linter.verify('const page = <a href="https://example.com/about">External</a>;', config, "fixture.jsx"),
      [],
    );
    assert.deepEqual(
      linter.verify('const page = <a href="/unrelated">Not a page in this app</a>;', config, "fixture.jsx"),
      [],
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
