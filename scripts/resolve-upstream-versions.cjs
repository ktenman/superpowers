#!/usr/bin/env node
// Resolve only the fork's deliberate Claude version omissions after a failed
// upstream merge. The caller must abort the merge if this script fails.
const { execFileSync } = require('node:child_process');
const { writeFileSync } = require('node:fs');
const { isDeepStrictEqual } = require('node:util');

const pluginPath = '.claude-plugin/plugin.json';
const marketPath = '.claude-plugin/marketplace.json';
const registryPath = '.version-bump.json';
const paths = [pluginPath, marketPath, registryPath];
const git = (...args) => execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const requireShape = (condition, path) => {
  if (!condition) throw new Error(`Unexpected format in ${path}`);
};
const claudeEntry = entry => (entry.path === pluginPath && entry.field === 'version')
  || (entry.path === marketPath && entry.field === 'plugins.0.version');

function omitVersions(path, value) {
  requireShape(object(value), path);
  if (path === registryPath) {
    requireShape(Array.isArray(value.files) && value.files.every(entry => object(entry)
      && typeof entry.path === 'string' && typeof entry.field === 'string'), path);
    // A changed registry layout needs a human, rather than leaving a declaration
    // that would restore the version we just omitted.
    const claude = value.files.filter(entry => [pluginPath, marketPath].includes(entry.path));
    requireShape(claude.every(claudeEntry)
      && new Set(claude.map(entry => entry.path)).size === claude.length, path);
    value.files = value.files.filter(entry => !claudeEntry(entry));
  } else {
    let plugin = value;
    if (path === marketPath) {
      requireShape(value.name === 'superpowers-dev' && Array.isArray(value.plugins) && value.plugins.every(object)
        && value.plugins.filter(entry => entry.name === 'superpowers').length === 1, path);
      plugin = value.plugins[0];
    }
    requireShape(plugin?.name === 'superpowers'
      && (!Object.hasOwn(plugin, 'version') || typeof plugin.version === 'string'), path);
    delete plugin.version;
  }
  return value;
}

function readBlob(ref, path) {
  const hash = git('ls-tree', '-z', ref, '--', path).match(/^100644 blob ([a-f0-9]+)\t[^\0]+\0$/)?.[1];
  if (!hash) throw new Error(`Missing or non-regular file: ${path}`);
  return git('cat-file', 'blob', hash);
}

function render(path, upstream, stripped) {
  if (path !== registryPath) return `${JSON.stringify(stripped, null, 2)}\n`;
  // Registry entries intentionally occupy one line each. Remove only those
  // lines, preserving every other upstream line and its formatting.
  const text = upstream.split('\n').filter(line => {
    if (!/^\s*\{.*\},?\s*$/.test(line)) return true;
    try { return !claudeEntry(JSON.parse(line.trim().replace(/,$/, ''))); } catch { return true; }
  }).join('\n').replace(/,(\s*\])/g, '$1');
  requireShape(isDeepStrictEqual(JSON.parse(text), stripped), path);
  return text;
}

function resolve() {
  const conflicts = git('diff', '--name-only', '--diff-filter=U', '-z').split('\0').filter(Boolean);
  const unrelated = conflicts.find(path => !paths.includes(path));
  if (unrelated) throw new Error(`Unrelated conflict: ${unrelated}`);
  if (!conflicts.length) throw new Error('No version conflicts to resolve');
  const theirs = git('rev-parse', '--verify', 'MERGE_HEAD').trim();
  const bases = git('merge-base', '--all', 'HEAD', theirs).trim().split('\n');
  if (bases.length !== 1) throw new Error('Multiple merge bases require manual resolution');

  // Validate all three files before writing or staging any of them, including
  // files Git merged cleanly. Taking theirs must not discard other fork edits.
  const results = paths.map(path => {
    const [base, ours, upstream] = [bases[0], 'HEAD', theirs].map(ref => readBlob(ref, path));
    const expectedOurs = omitVersions(path, JSON.parse(base));
    if (!isDeepStrictEqual(JSON.parse(ours), expectedOurs)) {
      throw new Error(`Additional fork changes in ${path}; refusing to discard them`);
    }
    const stripped = omitVersions(path, JSON.parse(upstream));
    return [path, render(path, upstream, stripped)];
  });
  for (const [path, text] of results) writeFileSync(path, text);
  git('add', '--', ...paths);
  console.log('Resolved upstream Claude metadata while preserving the fork’s version omissions.');
}

try { resolve(); } catch (error) {
  console.error(`Cannot auto-resolve upstream versions: ${error.message}`);
  process.exitCode = 1;
}
