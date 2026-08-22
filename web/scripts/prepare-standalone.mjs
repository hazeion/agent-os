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

// Mentat uses unoptimized local images. Remove Next's optional native image
// optimizer so the standalone payload stays safe to ship in a universal wheel.
for (const packagePath of [
  resolve(standaloneRoot, "node_modules", "@img"),
  resolve(standaloneRoot, "node_modules", "sharp"),
]) {
  rmSync(packagePath, { force: true, recursive: true });
}

const routes = [
  { source: "index.html", output: "home.html", currentLabel: "Home" },
  { source: "agents.html", output: "agents.html", currentLabel: "Agents" },
  { source: "tasks.html", output: "tasks.html", currentLabel: "Tasks" },
  { source: "runs.html", output: "runs.html", currentLabel: "Runs" },
];
const renderedAppRoot = resolve(nextRoot, "server", "app");
const shellOutputRoot = resolve(standaloneRoot, "public", "shell");
const frameworkScriptPattern = /<script\b[^>]*>[\s\S]*?<\/script>/giu;
const scriptPreloadPattern = /<link\b(?=[^>]*\brel="(?:modulepreload|preload)")(?=[^>]*\bas="script")[^>]*>/giu;

mkdirSync(shellOutputRoot, { recursive: true });

for (const route of routes) {
  const renderedRoute = resolve(renderedAppRoot, route.source);
  if (!existsSync(renderedRoute)) {
    throw new Error(`Next.js did not prerender the App Router route ${route.source}`);
  }

  const shell = readFileSync(renderedRoute, "utf8")
    .replace(scriptPreloadPattern, "")
    .replace(frameworkScriptPattern, (script) => (
      /data-mentat-(?:preference-preload|shell-runtime)/u.test(
        script.slice(0, script.indexOf(">") + 1),
      )
        ? script
        : ""
    ));

  const scripts = shell.match(/<script\b[^>]*\bsrc="[^"]+"[^>]*>/giu) ?? [];
  const scriptPaths = scripts.map((script) => script.match(/\bsrc="([^"]+)"/iu)?.[1]);
  if (
    scripts.length !== 2
    || JSON.stringify(scriptPaths) !== JSON.stringify(["/preference-preload.js", "/shell-runtime.js"])
    || !shell.includes('data-ui-shell="emerald"')
    || !shell.includes(`aria-current="page"`)
    || !shell.includes(`>${route.currentLabel}</strong>`)
    || !/href="\/_next\/static\/(?:chunks|css)\/[^"']+\.css/iu.test(shell)
    || shell.includes("self.__next_f")
    || /_next\/static\/(?:chunks|webpack)\/[^"']+\.js/iu.test(shell)
  ) {
    throw new Error(`The static Emerald shell route ${route.output} failed its no-hydration contract`);
  }

  writeFileSync(resolve(shellOutputRoot, route.output), shell, {
    encoding: "utf8",
    mode: 0o644,
  });
}
