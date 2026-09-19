#!/usr/bin/env node
/**
 * Syntax-check every static JS file (mirrors the CI validate-js step).
 * Exit non-zero on the first syntax error, printing the file and message.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const jsDir = path.join(__dirname, '..', 'static', 'js');
const files = [];

function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else if (entry.name.endsWith('.js')) files.push(full);
  }
}
walk(jsDir);

let errors = 0;
for (const f of files) {
  try {
    execFileSync(process.execPath, ['--input-type=module', '--check'], {
      input: fs.readFileSync(f, 'utf8'),
      stdio: ['pipe', 'pipe', 'pipe'],
    });
  } catch (e) {
    errors++;
    console.error(`SYNTAX ERROR in ${path.relative(process.cwd(), f)}:`);
    console.error(String(e.stderr || e.message).split('\n').slice(0, 5).join('\n'));
    console.error('');
  }
}
if (errors > 0) {
  console.error(`FAILED: ${errors} file(s) have syntax errors.`);
  process.exit(1);
}
console.log(`All ${files.length} JS files passed syntax validation.`);
