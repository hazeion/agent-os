import { existsSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { extname } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const SOURCE_EXTENSIONS = [".ts", ".tsx", ".mts", ".cts"];

function localCandidate(specifier, parentURL) {
  if (specifier.startsWith("@/")) {
    return new URL(`../src/${specifier.slice(2)}`, import.meta.url);
  }
  if (
    (specifier.startsWith("./") || specifier.startsWith("../"))
    && parentURL?.startsWith("file:")
  ) {
    return new URL(specifier, parentURL);
  }
  return null;
}

export async function resolve(specifier, context, nextResolve) {
  const candidate = localCandidate(specifier, context.parentURL);
  if (candidate !== null) {
    const candidates = extname(candidate.pathname)
      ? [candidate]
      : SOURCE_EXTENSIONS.map((extension) => new URL(`${candidate.href}${extension}`));
    for (const resolved of candidates) {
      if (existsSync(fileURLToPath(resolved))) {
        return { shortCircuit: true, url: resolved.href };
      }
    }
  }
  return nextResolve(specifier, context);
}

export async function load(url, context, nextLoad) {
  if (SOURCE_EXTENSIONS.some((extension) => url.endsWith(extension))) {
    const source = await readFile(new URL(url), "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        jsx: ts.JsxEmit.ReactJSX,
        module: ts.ModuleKind.ESNext,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: fileURLToPath(url),
    });
    return { format: "module", shortCircuit: true, source: output.outputText };
  }
  return nextLoad(url, context);
}
