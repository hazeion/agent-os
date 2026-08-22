import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const nextRoot = resolve(projectRoot, ".next");
const standaloneRoot = resolve(nextRoot, "standalone");
const serverEntry = resolve(standaloneRoot, "server.js");

if (!existsSync(serverEntry)) {
  throw new Error("Next.js did not produce .next/standalone/server.js");
}

function replaceDirectory(source, destination) {
  if (!existsSync(source)) return;
  rmSync(destination, { force: true, recursive: true });
  mkdirSync(destination, { recursive: true });
  cpSync(source, destination, { recursive: true });
}

replaceDirectory(resolve(nextRoot, "static"), resolve(standaloneRoot, ".next", "static"));
replaceDirectory(resolve(projectRoot, "public"), resolve(standaloneRoot, "public"));

const renderedAppShell = resolve(nextRoot, "server", "app", "index.html");
if (!existsSync(renderedAppShell)) {
  throw new Error("Next.js did not prerender the App Router foundation shell");
}
const frameworkScriptPattern = /<script\b[^>]*>[\s\S]*?<\/script>/giu;
const scriptPreloadPattern = /<link\b(?=[^>]*\brel="preload")(?=[^>]*\bas="script")[^>]*>/giu;
const foundationShell = readFileSync(renderedAppShell, "utf8")
  .replace(scriptPreloadPattern, "")
  .replace(frameworkScriptPattern, (script) => (
    script.slice(0, script.indexOf(">") + 1).includes("data-mentat-foundation-status")
      ? script
      : ""
  ));
const remainingScripts = foundationShell.match(/<script\b/giu) ?? [];
if (
  remainingScripts.length !== 1
  || !foundationShell.includes('src="/foundation-status.js"')
  || !foundationShell.includes('href="/_next/static/chunks/')
  || foundationShell.includes("self.__next_f")
  || /_next\/static\/chunks\/[^"']+\.js/iu.test(foundationShell)
) {
  throw new Error("The static foundation shell did not satisfy the no-hydration contract");
}
writeFileSync(
  resolve(standaloneRoot, "public", "foundation.html"),
  foundationShell,
  { encoding: "utf8", mode: 0o644 },
);
