import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('../..', import.meta.url));
const workflow = readFileSync(join(root, '.github/workflows/sync-upstream.yml'), 'utf8');
const mergeStep = workflow.split('      - name: Attempt the merge\n')[1]
  .split('\n      - name:')[0].split('        run: |\n')[1]
  .split('\n').map(line => line.replace(/^          /, '')).join('\n');
const resolver = join(root, 'scripts/resolve-upstream-versions.cjs');
const pluginPath = '.claude-plugin/plugin.json';
const marketPath = '.claude-plugin/marketplace.json';
const registryPath = '.version-bump.json';
const paths = [pluginPath, marketPath, registryPath];

function command(cwd, executable, args, env = {}) {
  return spawnSync(executable, args, {
    cwd, encoding: 'utf8', env: { ...process.env, GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', ...env },
  });
}

function git(cwd, ...args) {
  const result = command(cwd, 'git', args);
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return result.stdout.trim();
}

function write(cwd, path, value) {
  mkdirSync(dirname(join(cwd, path)), { recursive: true });
  writeFileSync(join(cwd, path), typeof value === 'string' ? value : `${JSON.stringify(value, null, 2)}\n`);
}

function read(cwd, path) { return JSON.parse(readFileSync(join(cwd, path), 'utf8')); }

function fixture(t, { forkEdit, upstreamEdit } = {}) {
  const cwd = mkdtempSync(join(tmpdir(), 'superpowers-upstream-'));
  t.after(() => rmSync(cwd, { recursive: true, force: true }));
  git(cwd, 'init', '-b', 'fork');
  git(cwd, 'config', 'user.name', 'Sync test');
  git(cwd, 'config', 'user.email', 'sync@example.invalid');
  write(cwd, pluginPath, { name: 'superpowers', description: 'Skills', version: '1.0.0', author: { name: 'Original' } });
  write(cwd, marketPath, { name: 'superpowers-dev', plugins: [{ name: 'superpowers', description: 'Skills', version: '1.0.0', source: './' }] });
  write(cwd, registryPath, '{\n  "files": [\n    { "path": "package.json", "field": "version" },\n    { "path": ".claude-plugin/plugin.json", "field": "version" },\n    { "path": "gemini-extension.json", "field": "version" },\n    { "path": ".claude-plugin/marketplace.json", "field": "plugins.0.version" }\n  ],\n  "audit": { "exclude": ["CHANGELOG.md"] }\n}\n');
  write(cwd, 'package.json', { name: 'superpowers', version: '1.0.0', description: 'Skills', type: 'module', main: 'index.js' });
  write(cwd, 'gemini-extension.json', { version: '1.0.0' });
  write(cwd, 'skills/example/SKILL.md', 'Original skill\n');
  // The actual helper runs inside the scratch checkout, as it does in CI.
  write(cwd, 'scripts/resolve-upstream-versions.cjs', readFileSync(resolver, 'utf8'));
  git(cwd, 'add', '.');
  git(cwd, 'commit', '-m', 'upstream base');
  git(cwd, 'branch', 'upstream');
  const plugin = read(cwd, pluginPath); delete plugin.version; write(cwd, pluginPath, plugin);
  const market = read(cwd, marketPath); delete market.plugins[0].version; write(cwd, marketPath, market);
  write(cwd, registryPath, '{\n  "files": [\n    { "path": "package.json", "field": "version" },\n    { "path": "gemini-extension.json", "field": "version" }\n  ],\n  "audit": { "exclude": ["CHANGELOG.md"] }\n}\n');
  const pkg = read(cwd, 'package.json'); pkg.bin = { install: 'install.js' }; write(cwd, 'package.json', pkg);
  forkEdit?.(cwd);
  git(cwd, 'add', '.'); git(cwd, 'commit', '-m', 'omit Claude versions');
  const before = git(cwd, 'rev-parse', 'HEAD');
  git(cwd, 'switch', 'upstream');
  for (const path of [pluginPath, 'package.json', 'gemini-extension.json']) {
    const value = read(cwd, path); value.version = '1.1.0'; write(cwd, path, value);
  }
  const releaseMarket = read(cwd, marketPath); releaseMarket.plugins[0].version = '1.1.0'; write(cwd, marketPath, releaseMarket);
  upstreamEdit?.(cwd);
  git(cwd, 'add', '.'); git(cwd, 'commit', '-m', 'upstream release');
  git(cwd, 'switch', 'fork');
  return { cwd, before };
}

function attempt(cwd) {
  const result = command(cwd, 'bash', ['-e', '-o', 'pipefail', '-c', mergeStep], {
    TAG: 'upstream', BRANCH: 'sync-release', RUNNER_TEMP: cwd, GITHUB_OUTPUT: join(cwd, 'outputs'),
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  return readFileSync(join(cwd, 'outputs'), 'utf8');
}

function assertCoherent(cwd) {
  assert.equal(read(cwd, pluginPath).version, undefined);
  assert.equal(read(cwd, marketPath).plugins.find(plugin => plugin.name === 'superpowers').version, undefined);
  const entries = read(cwd, registryPath).files;
  assert.equal(entries.some(entry => [pluginPath, marketPath].includes(entry.path)), false);
  for (const entry of entries) {
    const value = entry.field.split('.').reduce((item, key) => item[key], read(cwd, entry.path));
    assert.equal(value, '1.1.0', `version drift in ${entry.path}`);
  }
  assert.deepEqual(read(cwd, 'package.json').bin, { install: 'install.js' });
  assert.equal(git(cwd, 'diff', '--name-only', '--diff-filter=U'), '');
}

// Fails if the workflow aborts every conflict instead of resolving version omissions.
test('version-only release finishes the merge and keeps the registry coherent', t => {
  const { cwd } = fixture(t);
  assert.match(attempt(cwd), /^clean=true$/m);
  assert.equal(git(cwd, 'rev-list', '--parents', '-n', '1', 'HEAD').split(' ').length, 3);
  assert.doesNotMatch(git(cwd, 'log', '-1', '--format=%B'), /^#/m);
  assertCoherent(cwd);
});

// Fails if taking our registry loses the new upstream entry, or reformatting it adds noise.
test('adjacent registry addition and new upstream metadata survive resolution', t => {
  const { cwd } = fixture(t, { upstreamEdit(cwd) {
    const text = readFileSync(join(cwd, registryPath), 'utf8');
    write(cwd, registryPath, text.replace('    { "path": ".claude-plugin/plugin.json"',
      '    { "path": "new-plugin.json", "field": "version" },\n    { "path": ".claude-plugin/plugin.json"'));
    write(cwd, 'new-plugin.json', { version: '1.1.0' });
    const plugin = read(cwd, pluginPath); plugin.newMetadata = { enabled: true }; write(cwd, pluginPath, plugin);
    const market = read(cwd, marketPath); market.plugins.push({ name: 'another-plugin', version: '8.0.0', source: './another' }); write(cwd, marketPath, market);
  } });
  assert.match(attempt(cwd), /^clean=true$/m);
  assertCoherent(cwd);
  assert.deepEqual(read(cwd, pluginPath).newMetadata, { enabled: true });
  assert.equal(read(cwd, marketPath).plugins[1].version, '8.0.0');
  assert.match(readFileSync(join(cwd, registryPath), 'utf8'), /^    \{ "path": "new-plugin.json", "field": "version" \},$/m);
});

test('a new Claude manifest registry entry is preserved with its version', t => {
  const { cwd } = fixture(t, { upstreamEdit(cwd) {
    write(cwd, '.claude-plugin/new-plugin.json', { version: '1.1.0' });
    write(cwd, registryPath, readFileSync(join(cwd, registryPath), 'utf8')
      .replace('    { "path": ".claude-plugin/plugin.json"',
        '    { "path": ".claude-plugin/new-plugin.json", "field": "version" },\n    { "path": ".claude-plugin/plugin.json"'));
  } });
  assert.match(attempt(cwd), /^clean=true$/m);
  assertCoherent(cwd);
  assert.deepEqual(read(cwd, registryPath).files.find(entry => entry.path === '.claude-plugin/new-plugin.json'),
    { path: '.claude-plugin/new-plugin.json', field: 'version' });
});

// Fails if auto-resolution hides unrelated conflicts or fails to abort the merge.
test('unrelated skill conflict aborts and reports every conflicted path', t => {
  const { cwd, before } = fixture(t, {
    forkEdit: cwd => write(cwd, 'skills/example/SKILL.md', 'Fork skill\n'),
    upstreamEdit: cwd => write(cwd, 'skills/example/SKILL.md', 'Upstream skill\n'),
  });
  assert.match(attempt(cwd), /^why=/m);
  assert.equal(git(cwd, 'rev-parse', 'HEAD'), before);
  assert.equal(git(cwd, 'diff', 'HEAD', '--', ...paths, 'skills'), '');
  assert.deepEqual(readFileSync(join(cwd, 'detail.txt'), 'utf8').trim().split('\n').sort(),
    [pluginPath, marketPath, 'skills/example/SKILL.md'].sort());
});

for (const path of paths) {
  // Fails if taking upstream would silently discard additional fork metadata.
  test(`other fork edits in ${path} refuse resolution without changing any conflict`, t => {
    const { cwd } = fixture(t, { forkEdit(cwd) {
      const value = read(cwd, path); value.forkMetadata = 'keep me'; write(cwd, path, value);
    } });
    const merge = command(cwd, 'git', ['merge', '--no-edit', 'upstream']);
    assert.equal(merge.status, 1);
    const originalIndex = git(cwd, 'ls-files', '--stage');
    const originalFiles = paths.map(path => readFileSync(join(cwd, path), 'utf8'));
    const result = command(cwd, 'node', [resolver]);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /fork changes/i);
    assert.equal(git(cwd, 'ls-files', '--stage'), originalIndex);
    assert.deepEqual(paths.map(path => readFileSync(join(cwd, path), 'utf8')), originalFiles);
  });
}

for (const [name, upstreamEdit] of [
  ['a deleted manifest', cwd => rmSync(join(cwd, pluginPath))],
  ['a deleted registry', cwd => rmSync(join(cwd, registryPath))],
  ['malformed registry JSON', cwd => write(cwd, registryPath, '{ broken json\n')],
  ['an unexpected marketplace structure', cwd => write(cwd, marketPath, { name: 'superpowers-dev', plugins: {} })],
  ['multiline registry entries', cwd => write(cwd, registryPath, read(cwd, registryPath))],
]) {
  // Fails if an unsafe input is partially staged or the caller leaves a merge pending.
  test(`${name} aborts the workflow and restores the fork`, t => {
    const { cwd, before } = fixture(t, { upstreamEdit });
    assert.match(attempt(cwd), /^why=/m);
    assert.equal(git(cwd, 'rev-parse', 'HEAD'), before);
    assert.equal(git(cwd, 'diff', 'HEAD', '--', ...paths), '');
    assert.equal(git(cwd, 'diff', '--name-only', '--diff-filter=U'), '');
    assert.match(readFileSync(join(cwd, 'detail.txt'), 'utf8'), /\.claude-plugin\//);
  });
}
