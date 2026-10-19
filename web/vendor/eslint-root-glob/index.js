import { statSync } from "node:fs";
import { isAbsolute, parse } from "node:path";
import { globSync as globDirectories } from "tinyglobby";

// Next uses only this directory-root lookup, not the general fast-glob API.
export function globSync(pattern, options) {
  if (typeof pattern !== "string" || pattern.length === 0 || !options ||
      Object.keys(options).length !== 1 || options.onlyDirectories !== true) {
    throw new TypeError("Unsupported Next.js lint root glob request");
  }
  if (pattern === parse(pattern).root) {
    try {
      return statSync(pattern).isDirectory() ? [pattern] : [];
    } catch (error) {
      if (error.code === "ENOENT" || error.code === "ENOTDIR") return [];
      throw error;
    }
  }
  return globDirectories(pattern, {
    onlyDirectories: true,
    absolute: isAbsolute(pattern),
    expandDirectories: false,
  }).map((directory) => directory.replace(/\/$/, ""));
}
