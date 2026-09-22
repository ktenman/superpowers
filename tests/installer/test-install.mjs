import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { chmodSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { after, test } from 'node:test';

const installer = fileURLToPath(new URL('../../scripts/install.js', import.meta.url));
const id = 'superpowers@superpowers-dev';

test('fork Claude updates remain commit-derived across upstream version bumps', () => {
  const read = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
  assert.equal(read('.claude-plugin/plugin.json').version, undefined, 'a static version keeps fork-only Git revisions stale');
  const marketplace = read('.claude-plugin/marketplace.json');
  assert.equal(marketplace.plugins.find(p => p.name === 'superpowers').version, undefined);
  assert.ok(!read('.version-bump.json').files.some(f =>
    (f.path === '.claude-plugin/plugin.json' && f.field === 'version')
    || (f.path === '.claude-plugin/marketplace.json' && f.field === 'plugins.0.version')),
    'release bumps must not restore fixed Claude versions');
});

// One fake CLI for every test: macOS scans each newly written executable on its
// first run, so tests only symlink it. The link's name selects the CLI and its
// directory holds that test's fixtures and call log.
const fakeDir = mkdtempSync(join(tmpdir(), 'superpowers fake cli '));
after(() => rmSync(fakeDir, { recursive: true, force: true }));
const fake = join(fakeDir, 'fake-cli');
writeFileSync(fake, `#!${process.execPath}
const fs = require('node:fs');
const path = require('node:path');
const cli = path.basename(process.argv[1]);
const log = path.join(path.dirname(process.argv[1]), 'calls.jsonl');
const fixture = path.join(path.dirname(process.argv[1]), cli + '.json');
const args = process.argv.slice(2);
fs.appendFileSync(log, JSON.stringify([cli, ...args]) + '\\n');
const responses = JSON.parse(fs.readFileSync(fixture, 'utf8'));
if (args[0] === '--version' && !responses['--version']) { console.log('fixture 1.0'); process.exit(0); }
const entry = responses[args.join(' ')];
const response = Array.isArray(entry) ? entry.shift() : entry;
if (Array.isArray(entry)) fs.writeFileSync(fixture, JSON.stringify(responses));
if (!response) { console.error('Unexpected command: ' + args.join(' ')); process.exit(99); }
if (response.stderr) console.error(response.stderr);
if (response.stdout !== undefined) console.log(response.stdout);
else if (response.json !== undefined) console.log(JSON.stringify(response.json));
if (response.ignoreTerm) {
  process.on('SIGTERM', () => {});
  setTimeout(() => {
    fs.appendFileSync(log, JSON.stringify(['survived-timeout']) + '\\n');
    process.exit(0);
  }, 1000);
} else process.exit(response.status || 0);
`);
chmodSync(fake, 0o755);

// Substitute only the external CLI boundary. Each fixture is an observed native
// command/response contract; the actual installer runs as a separate process.
function run(t, commands = {}, { args = [], settings, shortTimeout = false } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'superpowers installer '));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  const log = join(dir, 'calls.jsonl');
  if (settings !== undefined) writeFileSync(join(dir, 'settings.json'), typeof settings === 'string' ? settings : JSON.stringify(settings));
  for (const [cli, responses] of Object.entries(commands)) {
    writeFileSync(join(dir, `${cli}.json`), JSON.stringify(responses));
    symlinkSync(fake, join(dir, cli));
  }
  const preload = join(dir, 'short-timeout.mjs');
  if (shortTimeout) {
    // Shorten the real subprocess timeout for this regression, without adding
    // test knobs to the installer. The fixture process really ignores SIGTERM.
    writeFileSync(preload, `import cp from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
const original = cp.spawnSync;
cp.spawnSync = (cli, args, options) => original(cli, args, { ...options, timeout: cli === 'claude' ? 500 : options.timeout });
syncBuiltinESMExports();`);
  }
  const result = spawnSync(process.execPath, [...(shortTimeout ? ['--import', preload] : []), installer, ...args], {
    cwd: dir, env: { ...process.env, PATH: dir, COPILOT_HOME: dir }, encoding: 'utf8', timeout: 10_000,
  });
  let calls = [];
  try { calls = readFileSync(log, 'utf8').trim().split('\n').map(JSON.parse); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  return { ...result, output: result.stdout + result.stderr, calls };
}

function assertReadOnly(calls) {
  assert.ok(calls.every(c => c[1] === '--version' || c.includes('list')), JSON.stringify(calls));
}

function assertNoReinstall(calls) {
  assert.ok(!calls.some(c => c.includes('install') || c.includes('enable') || c.includes('remove')), JSON.stringify(calls));
}

const copilotPlugin = { name: 'superpowers', marketplace: 'superpowers-dev', enabled: true, source: 'installed' };
function copilotState(plugin = copilotPlugin) {
  return {
    'plugin marketplace list --json': { json: [{ name: 'superpowers-dev', source: 'GitHub: ktenman/superpowers', isDefault: false }] },
    'plugin list --json': { json: [plugin] },
    'plugin marketplace update superpowers-dev': { stdout: 'Updated marketplace' },
    [`plugin update ${id}`]: { stdout: 'Updated plugin' },
  };
}
const copilotSettings = { extraKnownMarketplaces: { 'superpowers-dev': { source: { source: 'github', repo: 'ktenman/superpowers', ref: 'main' } } } };

test('installs Copilot with a marketplace-qualified selector and explicit ref', t => {
  const result = run(t, { copilot: {
    'plugin marketplace list --json': { json: [] },
    'plugin list --json': [{ json: [] }, { json: [copilotPlugin] }],
    'plugin marketplace add ktenman/superpowers#feature/install': { stdout: 'Added marketplace' },
    [`plugin install ${id}`]: { stdout: 'Installed plugin' },
  } }, { args: ['--ref', 'feature/install'] });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /copilot: installed/);
  assert.ok(result.calls.some(c => c.join(' ') === `copilot plugin install ${id}`));
});

test('Copilot rerun uses qualified update and preserves disabled state', t => {
  const result = run(t, { copilot: copilotState({ ...copilotPlugin, enabled: false }) }, { settings: copilotSettings });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /copilot: updated.*disabled/);
  assertNoReinstall(result.calls);
});

test('Copilot reads native JSONC settings without damaging string literals', t => {
  const settings = `// Native user settings\n${JSON.stringify(copilotSettings).slice(0, -1)}, "comment": "https://example.test/,}/* literal */", /* allowed */ }`;
  const result = run(t, { copilot: copilotState() }, { settings });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /copilot: updated/);
});

test('Copilot refuses a different ref even when list reports the right repository', t => {
  const settings = structuredClone(copilotSettings);
  settings.extraKnownMarketplaces['superpowers-dev'].source.ref = 'dev';
  const result = run(t, { copilot: copilotState() }, { settings });
  assert.equal(result.status, 1, result.output);
  assert.ok(result.output.includes('found github ktenman/superpowers#dev'), result.output);
  assert.match(result.output, /copilot plugin marketplace remove superpowers-dev --force/);
  assertReadOnly(result.calls);
});

test('Copilot refuses an unverifiable registration instead of treating it as absent', t => {
  const result = run(t, { copilot: copilotState() });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /settings.json/);
  assertReadOnly(result.calls);
});

test('--help explains remote main and makes no CLI calls', t => {
  const result = run(t, { claude: {} }, { args: ['--help'] });
  assert.equal(result.status, 0, result.output);
  assert.match(result.stdout, /ktenman\/superpowers/);
  assert.match(result.stdout, /main/);
  assert.match(result.stdout, /--ref/);
  assert.deepEqual(result.calls, []);
});

test('no installed CLIs is an actionable failure', t => {
  const result = run(t);
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /No supported CLI/);
});

test('installs Claude from GitHub with explicit user scope', t => {
  const result = run(t, { claude: {
    'plugin marketplace list --json': { json: [] },
    'plugin list --json': [{ json: [] }, { json: [{ id, scope: 'user', enabled: true, version: 'abcdef123456' }] }],
    'plugin marketplace add https://github.com/ktenman/superpowers.git#main --scope user': { stdout: 'Added marketplace' },
    [`plugin install ${id} --scope user --json`]: { json: { outcome: 'ok', command: 'install' } },
  } });
  assert.equal(result.status, 0, result.output);
  assert.ok(result.calls.some(c => c.join(' ') === `claude plugin install ${id} --scope user --json`));
  assert.match(result.output, /claude: installed/);
});

test('installs Codex using add with the selected ref', t => {
  const result = run(t, { codex: {
    'plugin marketplace list --json': { json: { marketplaces: [] } },
    'plugin list --json': [{ json: { installed: [], available: [] } }, { json: { installed: [{ pluginId: id, enabled: true, installed: true }], available: [] } }],
    'plugin marketplace add ktenman/superpowers --ref feature/install --json': { json: { marketplaceName: 'superpowers-dev', alreadyAdded: false } },
    [`plugin add ${id} --json`]: { json: { pluginId: id, version: '6.4.1' } },
  } }, { args: ['--ref', 'feature/install'] });
  assert.equal(result.status, 0, result.output);
  assert.ok(result.calls.some(c => c.join(' ') === `codex plugin add ${id} --json`));
  assert.match(result.output, /codex: installed/);
});

const claudeMarketplace = { name: 'superpowers-dev', source: 'git', url: 'https://github.com/ktenman/superpowers.git', ref: 'main' };
const claudePlugin = { id, scope: 'user', version: 'abcdef123456', enabled: true };
function claudeState(marketplace = claudeMarketplace, plugin = claudePlugin) {
  return {
    'plugin marketplace list --json': { json: [marketplace] },
    'plugin list --json': { json: [plugin] },
    'plugin marketplace update superpowers-dev': { stdout: 'Updated marketplace' },
    [`plugin update ${id} --scope user --json`]: { json: { outcome: 'ok', updateOutcome: 'updated' } },
  };
}
const codexMarketplace = { name: 'superpowers-dev', marketplaceSource: { sourceType: 'git', source: 'https://github.com/ktenman/superpowers.git' } };
const codexPlugin = { pluginId: id, installed: true, enabled: true, version: '6.4.1' };
function codexState(plugin = codexPlugin) {
  return {
    'plugin marketplace list --json': { json: { marketplaces: [codexMarketplace] } },
    'plugin list --json': { json: { installed: [plugin], available: [] } },
    'plugin marketplace add ktenman/superpowers --ref main --json': { json: { marketplaceName: 'superpowers-dev', alreadyAdded: true } },
    'plugin marketplace upgrade superpowers-dev --json': { json: { selectedMarketplaces: ['superpowers-dev'], upgradedRoots: [], errors: [] } },
  };
}

for (const [marketplace, found] of [
  [{ ...claudeMarketplace, url: 'https://github.com/obra/superpowers.git' }, 'git https://github.com/obra/superpowers.git#main'],
  [{ ...claudeMarketplace, ref: 'another-branch' }, 'git https://github.com/ktenman/superpowers.git#another-branch'],
]) {
  test(`Claude refuses a conflicting source/ref: ${JSON.stringify(marketplace)}`, t => {
    const result = run(t, { claude: claudeState(marketplace) });
    assert.equal(result.status, 1, result.output);
    assert.ok(result.output.includes(`found ${found}`), result.output);
    assert.match(result.output, /claude plugin marketplace remove superpowers-dev/);
    assertReadOnly(result.calls);
  });
}

// scripts/install.sh registered the checkout itself; Claude loads it in place.
const claudeDirectory = { name: 'superpowers-dev', source: 'directory', path: '/local/checkout', installLocation: '/local/checkout' };

test('Claude skips an enabled local directory install without touching it', t => {
  const result = run(t, { claude: claudeState(claudeDirectory) });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /claude: skipped \(.*\/local\/checkout/);
  assert.match(result.output, /claude plugin marketplace remove superpowers-dev/);
  assertReadOnly(result.calls);
});

for (const [state, plugins] of [['disabled', [{ ...claudePlugin, enabled: false }]], ['not installed', []]]) {
  test(`Claude refuses a local directory install whose plugin is ${state}`, t => {
    const commands = claudeState(claudeDirectory);
    commands['plugin list --json'] = { json: plugins };
    const result = run(t, { claude: commands });
    assert.equal(result.status, 1, result.output);
    assert.ok(result.output.includes('found directory /local/checkout'), result.output);
    assertReadOnly(result.calls);
  });
}

test('Claude rerun updates a disabled plugin without enabling it', t => {
  const result = run(t, { claude: claudeState(claudeMarketplace, { ...claudePlugin, enabled: false }) });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /claude: updated.*disabled/);
  assertNoReinstall(result.calls);
});

test('Codex rerun refreshes a disabled plugin without repeating plugin add', t => {
  const result = run(t, { codex: codexState({ ...codexPlugin, enabled: false }) });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /codex: updated.*disabled/);
  assert.ok(!result.calls.some(c => c[1] === 'plugin' && c[2] === 'add'));
});

test('Codex refuses a local marketplace and names it', t => {
  const commands = codexState();
  commands['plugin marketplace list --json'] = { json: { marketplaces: [
    { name: 'superpowers-dev', root: '/local/checkout', marketplaceSource: { sourceType: 'local', source: '/local/checkout' } },
  ] } };
  const result = run(t, { codex: commands });
  assert.equal(result.status, 1, result.output);
  assert.ok(result.output.includes('found local /local/checkout'), result.output);
  assert.match(result.output, /codex plugin remove superpowers@superpowers-dev[\s\S]*codex plugin marketplace remove superpowers-dev/);
  assertReadOnly(result.calls);
});

test('Codex native ref conflict stops before refresh and suggests explicit migration', t => {
  const commands = codexState();
  commands['plugin marketplace add ktenman/superpowers --ref main --json'] = { status: 1, stderr: "marketplace 'superpowers-dev' is already added from a different source; remove it before adding this source" };
  const result = run(t, { codex: commands });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /codex plugin marketplace remove superpowers-dev/);
  assert.match(result.output, /codex plugin remove superpowers@superpowers-dev[\s\S]*codex plugin marketplace remove superpowers-dev/);
  assert.ok(!result.calls.some(c => c.includes('upgrade') || c.includes('remove')));
});

test('Claude refresh failure stops before a potentially stale plugin update', t => {
  const commands = claudeState();
  commands['plugin marketplace update superpowers-dev'] = { status: 1, stderr: 'source unreachable' };
  const result = run(t, { claude: commands, codex: codexState() });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /source unreachable/);
  assert.match(result.output, /codex: updated/);
  assert.ok(!result.calls.some(c => c[0] === 'claude' && c[1] === 'plugin' && c[2] === 'update'));
});

test('Codex refresh failure with plain text is reported before attempting JSON parsing', t => {
  const commands = codexState();
  commands['plugin marketplace upgrade superpowers-dev --json'] = { status: 1, stderr: 'Error: 1 upgrade failure(s) occurred.' };
  const result = run(t, { codex: commands });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /1 upgrade failure/);
  assert.doesNotMatch(result.output, /invalid JSON/);
  assert.doesNotMatch(result.output, /codex: updated/);
});

test('Codex refresh errors inside successful JSON are failures', t => {
  const commands = codexState();
  commands['plugin marketplace upgrade superpowers-dev --json'].json.errors = [{ marketplace: 'superpowers-dev', error: 'network unavailable' }];
  const result = run(t, { codex: commands });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /network unavailable/);
  assert.doesNotMatch(result.output, /codex: updated/);
});

test('a Claude failure does not prevent an independent Codex update', t => {
  const result = run(t, { claude: { 'plugin marketplace list --json': { status: 1, stderr: 'discovery denied' } }, codex: codexState() });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /discovery denied/);
  assert.match(result.output, /codex: updated/);
  assert.ok(!result.calls.some(c => c[0] === 'claude' && (c.includes('add') || c.includes('install'))));
});

for (const response of [{ stdout: 'not json' }, { json: {} }]) {
  test(`malformed discovery fails without mutation: ${JSON.stringify(response)}`, t => {
    const result = run(t, { claude: { 'plugin marketplace list --json': response, 'plugin list --json': { json: [] } } });
    assert.equal(result.status, 1, result.output);
    assert.match(result.output, /invalid JSON|expected an array/i);
    assertReadOnly(result.calls);
  });
}

test('a native JSON failure is not reported as installed', t => {
  const commands = claudeState();
  commands[`plugin update ${id} --scope user --json`] = { json: { outcome: 'error', message: 'plugin verification failed' } };
  const result = run(t, { claude: commands });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /plugin verification failed/);
  assert.doesNotMatch(result.output, /claude: updated/);
});

for (const args of [['--bogus'], ['--ref'], ['--ref', 'main;echo bad'], ['--ref', '--help']]) {
  test(`invalid arguments cause no CLI calls: ${args.join(' ')}`, t => {
    const result = run(t, { claude: {} }, { args });
    assert.equal(result.status, 1, result.output);
    assert.match(result.output, /Usage:/);
    assert.deepEqual(result.calls, []);
  });
}

test('success output from a native command still requires an installed plugin', t => {
  const commands = claudeState();
  commands['plugin list --json'] = [{ json: [claudePlugin] }, { json: [] }];
  const result = run(t, { claude: commands });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /not installed/);
  assert.doesNotMatch(result.output, /claude: updated/);
});

test('reports an unexpected enabled-state change instead of claiming it was preserved', t => {
  const commands = codexState();
  commands['plugin list --json'] = [{ json: { installed: [{ ...codexPlugin, enabled: false }] } }, { json: { installed: [codexPlugin] } }];
  const result = run(t, { codex: commands });
  assert.equal(result.status, 1, result.output);
  assert.match(result.output, /enabled state changed/);
  assert.doesNotMatch(result.output, /disabled, preserved/);
});

test('an existing marketplace with a missing plugin recovers on rerun', t => {
  const commands = codexState();
  commands['plugin list --json'] = [{ json: { installed: [] } }, { json: { installed: [codexPlugin] } }];
  commands[`plugin add ${id} --json`] = { json: { pluginId: id } };
  const result = run(t, { codex: commands });
  assert.equal(result.status, 0, result.output);
  assert.match(result.output, /codex: installed/);
  assert.ok(result.calls.some(c => c.includes('upgrade')));
  assert.ok(result.calls.some(c => c[1] === 'plugin' && c[2] === 'add'));
});

for (const step of ['--version', `plugin update ${id} --scope user --json`]) {
  test(`terminates a CLI ignoring SIGTERM at ${step} and continues other harnesses`, t => {
    const commands = claudeState();
    commands[step] = { ignoreTerm: true };
    const result = run(t, { claude: commands, codex: codexState() }, { shortTimeout: true });
    assert.equal(result.status, 1, result.output);
    assert.match(result.output, /ETIMEDOUT/);
    assert.match(result.output, /codex: updated/);
    assert.ok(!result.calls.some(c => c[0] === 'survived-timeout'), 'the timed-out CLI kept running after ignoring SIGTERM');
  });
}
