#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const repository = 'ktenman/superpowers';
const gitUrl = `https://github.com/${repository}.git`;

function command(cli, args) {
  const label = `${cli} ${args.join(' ')}`;
  const json = args.includes('--json');
  console.log(`> ${label}`);
  const result = spawnSync(cli, args, {
    encoding: 'utf8', stdio: ['inherit', json ? 'pipe' : 'inherit', 'inherit'],
    timeout: 120_000, killSignal: 'SIGKILL',
  });
  if (result.error || result.status !== 0) {
    throw new Error(`${label} failed: ${result.error?.message ?? `exit ${result.status}`}\n${result.stdout ?? ''}`);
  }
  if (!json) return;
  let value;
  try { value = JSON.parse(result.stdout); }
  catch { throw new Error(`${label} returned invalid JSON: ${result.stdout}`); }
  if (value?.outcome === 'error' || value?.errors?.length) {
    throw new Error(`${label} failed: ${JSON.stringify(value)}`);
  }
  return value;
}

function manifest(path) {
  return JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
}

function array(value, description) {
  if (!Array.isArray(value)) throw new Error(`${description}: expected an array; update the CLI if its plugin API differs`);
  return value;
}

function forkSource(source) {
  const pattern = new RegExp(String.raw`^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)?${repository}(?:\.git)?/?$`, 'i');
  return typeof source === 'string' && pattern.test(source);
}

function migration(cli, marketplace, id) {
  const remove = `${cli} plugin marketplace remove ${marketplace}${cli === 'copilot' ? ' --force' : ''}`;
  const commands = cli === 'codex' ? `codex plugin remove ${id}\n${remove}` : remove;
  return `To migrate, review the existing registration and explicitly remove it and its installed plugin(s):\n${commands}\nThen rerun the installer. These commands are not run automatically.`;
}

function describe(source) {
  const location = source?.url ?? source?.repo ?? source?.path;
  if (!location) return JSON.stringify(source) ?? 'no source';
  return `${source.source} ${location}${source.ref ? `#${source.ref}` : ''}`;
}

function requireFork(cli, marketplace, id, source, ref) {
  if (!['git', 'github'].includes(source?.source) || !forkSource(source.url ?? source.repo) || source.ref !== ref) {
    throw new Error(`Marketplace ${marketplace} does not match ${repository}#${ref} (found ${describe(source)}). ${migration(cli, marketplace, id)}`);
  }
}

function summary(cli, before, after) {
  if (!after) throw new Error(`${cli}: plugin is not installed after the native command completed`);
  if (typeof after.enabled !== 'boolean') throw new Error(`${cli}: plugin list did not report enabled state`);
  if (before && before.enabled !== after.enabled) throw new Error(`${cli}: enabled state changed unexpectedly; inspect it with ${cli} plugin list --json`);
  const state = after.enabled ? 'enabled' : before ? 'disabled, preserved' : 'disabled';
  console.log(`${cli}: ${before ? 'updated' : 'installed'} (${state}${after.version ? `, version ${after.version}` : ''}). Restart the harness to load the skills.`);
}

function installClaude(ref) {
  const marketplace = manifest('.claude-plugin/marketplace.json').name;
  const id = `${manifest('.claude-plugin/plugin.json').name}@${marketplace}`;
  const marketplaces = array(command('claude', ['plugin', 'marketplace', 'list', '--json']), 'claude marketplaces');
  const installedPlugin = () => array(command('claude', ['plugin', 'list', '--json']), 'claude plugins').find(p => p.id === id && p.scope === 'user');
  const existing = marketplaces.find(m => m.name === marketplace);
  const installed = installedPlugin();
  // Claude loads a directory marketplace in place, so an enabled plugin from a
  // local checkout already has its skills. Leave that registration alone.
  if (existing?.source === 'directory' && installed?.enabled) {
    console.log(`claude: skipped (${marketplace} is a local directory marketplace at ${existing.path}; Claude loads the skills live from that checkout, not from ${repository}#${ref}). ${migration('claude', marketplace, id)}`);
    return;
  }
  if (existing) {
    requireFork('claude', marketplace, id, existing, ref);
    command('claude', ['plugin', 'marketplace', 'update', marketplace]);
  } else {
    command('claude', ['plugin', 'marketplace', 'add', `${gitUrl}#${ref}`, '--scope', 'user']);
  }
  command('claude', ['plugin', installed ? 'update' : 'install', id, '--scope', 'user', '--json']);
  summary('claude', installed, installedPlugin());
}

function installCodex(ref) {
  const marketplace = manifest('.agents/plugins/marketplace.json').name;
  const id = `${manifest('.codex-plugin/plugin.json').name}@${marketplace}`;
  const marketplaces = array(command('codex', ['plugin', 'marketplace', 'list', '--json'])?.marketplaces, 'codex marketplaces');
  const installedPlugin = () => array(command('codex', ['plugin', 'list', '--json'])?.installed, 'codex plugins').find(p => p.pluginId === id);
  const existing = marketplaces.find(m => m.name === marketplace);
  const installed = installedPlugin();
  if (existing && (existing.marketplaceSource?.sourceType !== 'git' || !forkSource(existing.marketplaceSource?.source))) {
    throw new Error(`Marketplace ${marketplace} does not match ${repository} (found ${existing.marketplaceSource?.sourceType} ${existing.marketplaceSource?.source}). ${migration('codex', marketplace, id)}`);
  }
  // list omits the ref. Native add verifies the complete registration and
  // refuses a different ref without changing it; an identical add is a no-op.
  try {
    command('codex', ['plugin', 'marketplace', 'add', repository, '--ref', ref, '--json']);
  } catch (error) {
    throw new Error(`${error.message}${existing ? `\n${migration('codex', marketplace, id)}` : ''}`);
  }
  if (existing) command('codex', ['plugin', 'marketplace', 'upgrade', marketplace, '--json']);
  if (!installed) command('codex', ['plugin', 'add', id, '--json']);
  summary('codex', installed, installedPlugin());
}

function copilotSource(marketplace) {
  // Copilot's list JSON omits refs; its native settings are the only source of
  // that information. Read JSONC without changing it. CLI list migrates legacy
  // registrations into this file before we reach here.
  const path = join(process.env.COPILOT_HOME || join(homedir(), '.copilot'), 'settings.json');
  try {
    const json = readFileSync(path, 'utf8')
      .replace(/"(?:\\.|[^"\\])*"|\/\/[^\r\n]*|\/\*[\s\S]*?\*\//g, token => token.startsWith('"') ? token : ' ')
      .replace(/"(?:\\.|[^"\\])*"|,(\s*[}\]])/g, (token, trailing) => trailing ?? token);
    return JSON.parse(json).extraKnownMarketplaces?.[marketplace]?.source;
  } catch (error) {
    throw new Error(`Cannot verify the Copilot marketplace ref in ${path}: ${error.message}`);
  }
}

function installCopilot(ref) {
  const marketplace = manifest('.claude-plugin/marketplace.json').name;
  const name = manifest('.claude-plugin/plugin.json').name;
  const id = `${name}@${marketplace}`;
  const marketplaces = array(command('copilot', ['plugin', 'marketplace', 'list', '--json']), 'copilot marketplaces');
  const installedPlugin = () => array(command('copilot', ['plugin', 'list', '--json']), 'copilot plugins').find(p => p.name === name && p.marketplace === marketplace);
  const existing = marketplaces.find(m => m.name === marketplace);
  const installed = installedPlugin();
  if (existing) {
    requireFork('copilot', marketplace, id, copilotSource(marketplace), ref);
    command('copilot', ['plugin', 'marketplace', 'update', marketplace]);
  } else {
    command('copilot', ['plugin', 'marketplace', 'add', `${repository}#${ref}`]);
  }
  command('copilot', ['plugin', installed ? 'update' : 'install', id]);
  summary('copilot', installed, installedPlugin());
}

function main(args) {
  if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
    console.log(`Usage: npx github:${repository} [--ref BRANCH_OR_TAG]

Install or update ${repository} from main in each installed CLI:
Claude Code, Codex and Copilot CLI. Requires Node.js and Git on PATH.

--ref BRANCH_OR_TAG  Select another remote branch or tag for the plugins.
-h, --help           Show this help without changing anything.

Reruns refresh existing installations and preserve disabled plugins.
Different marketplace sources/refs require explicit native migration.
Missing CLIs are skipped. No CLI found or any failure exits with status 1.
Native commands may require authentication or a terminal; diagnostics are
preserved and commands time out after two minutes. Fix the failure and rerun.
Installation does not guarantee session-start bootstrap execution.

Docs: https://github.com/${repository}/blob/main/docs/fork-install.md`);
    return 0;
  }
  const ref = args.length === 0 ? 'main' : args.length === 2 && args[0] === '--ref' ? args[1] : undefined;
  if (!ref || !/^[A-Za-z0-9][A-Za-z0-9._/-]*$/.test(ref) || ref.includes('..')) {
    console.error('Usage: superpowers-install [--ref BRANCH_OR_TAG] (see --help)');
    return 1;
  }
  let found = 0;
  let failed = 0;
  for (const [cli, install] of [['claude', installClaude], ['codex', installCodex], ['copilot', installCopilot]]) {
    const probe = spawnSync(cli, ['--version'], { encoding: 'utf8', timeout: 10_000, killSignal: 'SIGKILL' });
    if (probe.error?.code === 'ENOENT') {
      console.log(`${cli}: skipped (not on PATH)`);
      continue;
    }
    found++;
    try {
      if (probe.error || probe.status !== 0) throw new Error(`Cannot run ${cli}: ${probe.error?.message ?? probe.stderr}`);
      install(ref);
    } catch (error) {
      failed++;
      console.error(`${cli}: FAILED: ${error.message}`);
    }
  }
  if (!found) console.error('No supported CLI found. Install Claude Code, Codex or Copilot CLI first.');
  return failed || !found ? 1 : 0;
}

process.exitCode = main(process.argv.slice(2));
