#!/usr/bin/env node
/**
 * validate-imports.js
 * Checks that every named import from local ES modules actually
 * resolves to an export in the target file.
 *
 * Usage: node scripts/validate-imports.js [file1.js file2.js ...]
 *   - With args: checks only files that import from the listed files
 *   - No args: checks all .js files under static/js/
 *
 * Exit code 0 = all OK, 1 = broken imports found.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const JS_ROOT = path.join(ROOT, "static", "js");

// Collect all JS files to check
let filesToCheck = process.argv.slice(2);
if (filesToCheck.length === 0) {
  filesToCheck = collectJSFiles(JS_ROOT);
}

// Build export map: filePath -> Set of exported names
const exportCache = new Map();

function getExports(filePath) {
  if (exportCache.has(filePath)) return exportCache.get(filePath);
  let content;
  try {
    content = fs.readFileSync(filePath, "utf8");
  } catch {
    exportCache.set(filePath, new Set());
    return new Set();
  }
  const exports = new Set();
  const re = /export\s+(?:async\s+)?(?:function|const|let|var|class)\s+(\w+)/g;
  let m;
  while ((m = re.exec(content)) !== null) {
    exports.add(m[1]);
  }
  const blockRe = /export\s+\{([^}]+)\}/g;
  while ((m = blockRe.exec(content)) !== null) {
    const names = m[1].split(",").map(s => s.trim());
    for (const n of names) {
      const parts = n.split(/\s+as\s+/);
      exports.add(parts[parts.length - 1].trim());
    }
  }
  exportCache.set(filePath, exports);
  return exports;
}

function resolveImportPath(fromFile, spec) {
  const dir = path.dirname(fromFile);
  let target = path.resolve(dir, spec);
  if (!path.extname(target)) target += ".js";
  return target;
}

function collectJSFiles(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      results.push(...collectJSFiles(full));
    } else if (entry.name.endsWith(".js")) {
      results.push(full);
    }
  }
  return results;
}

const errors = [];

for (const filePath of filesToCheck) {
  const absPath = path.isAbsolute(filePath) ? filePath : path.resolve(".", filePath);
  let content;
  try {
    content = fs.readFileSync(absPath, "utf8");
  } catch {
    continue;
  }

  const relFrom = path.relative(ROOT, absPath).replace(/\\/g, "/");

  // Strip block comments before parsing imports
  const noBlockComments = content.replace(/\/\*[\s\S]*?\*\//g, "");

  // Parse import { ... } from '...' lines (handles multi-import lines with ;)
  // Only match lines that start with import (possibly indented, not in comments)
  const importRe = /(?:^|\n)\s*import\s*\{([^}]+)\}\s*from\s*['"]([^'"]+)['"]/g;
  let m;
  while ((m = importRe.exec(noBlockComments)) !== null) {
    const names = m[1].split(",").map(s => s.trim().split(/\s+as\s+/)[0].trim()).filter(Boolean);
    const spec = m[2];

    if (!spec.startsWith(".") && !spec.startsWith("/")) continue;

    const targetPath = resolveImportPath(absPath, spec);

    if (!fs.existsSync(targetPath)) {
      errors.push(`  ${relFrom}: imports from '${spec}' -> FILE NOT FOUND: ${targetPath}`);
      continue;
    }

    const exports = getExports(targetPath);
    const relTarget = path.relative(ROOT, targetPath).replace(/\\/g, "/");

    for (const name of names) {
      if (!exports.has(name)) {
        errors.push(`  ${relFrom}: imports '${name}' from '${relTarget}' but it is NOT exported`);
      }
    }
  }
}

if (errors.length > 0) {
  console.error("\nBROKEN IMPORTS FOUND:\n");
  for (const e of errors) console.error(e);
  console.error(`\n${errors.length} broken import(s) detected. Fix them before committing.\n`);
  process.exit(1);
} else {
  console.log(`All imports validated across ${filesToCheck.length} file(s).`);
}
