# Install the ktenman fork

Install the fork's skills into every supported CLI found on PATH:

```sh
npx github:ktenman/superpowers
```

This replaces `scripts/install.sh`. It needs Node.js, npm, Git and at least one
of Claude Code, Codex or GitHub Copilot CLI. It adds no npm dependencies and
installs no CLI globally. From an existing checkout, use `node scripts/install.js`.
Both commands install the **remote fork's `main` branch**, independent of the
checkout's current branch. Native plugin installation includes the fork-only
`autoresearch`, `ai-checker` and `akit-lookup` skills.

Run the same command again to update. Missing CLIs are skipped; no available CLI,
failed discovery, an incompatible registration or an update failure exits 1.
Failures in one CLI do not prevent attempts in the others. Completed steps stay
in place, so rerun after fixing the reported failure. Disabled plugins stay
disabled. Restart the harness after an update.

Use `--help` for options. To test a feature branch, select both the installer
revision and the native plugin source:

```sh
npx github:ktenman/superpowers#issue-16-npx-installer --ref issue-16-npx-installer
```

`--ref` accepts a branch or tag. A full commit SHA is not portable across these
CLIs: Claude's marketplace clone expects a branch or tag. Changing a registered
ref later requires the same explicit migration as changing its source.

## Native installation and updates

The installer reads the plugin and marketplace names from the packaged manifests.
Currently they are `superpowers@superpowers-dev` for all three CLIs.

| CLI | First installation | Existing installation |
| --- | --- | --- |
| Claude Code | Marketplace add, plugin install in user scope | Marketplace update, plugin update in user scope |
| Codex | Marketplace add, plugin add | Validate registration with marketplace add, then marketplace upgrade; plugin add only if missing |
| Copilot CLI | Marketplace add, plugin install with the full identifier | Marketplace update, plugin update with the full identifier |

The wrapper never removes a plugin or marketplace and never writes harness
configuration directly. Copilot's marketplace list omits its Git ref, so the
wrapper reads `settings.json` under `COPILOT_HOME` (default `~/.copilot`) to verify
the registration. Native CLI commands remain responsible for all configuration
changes, including their own legacy-settings migration. An unverifiable source
fails without an automatic replacement.

npm may ask to download the installer. For unattended downloads, use
`npx --yes github:ktenman/superpowers`; that only answers npm's prompt. Native CLI
prompts, authentication, policy restrictions and hook trust remain native. The
wrapper retains command diagnostics and stops a command after two minutes.
Resolve the reported native failure directly, then rerun. A fresh public-repo
installation required no login for the plugin-management commands tested here;
running an agent session still requires the harness's authentication.

## Existing local installations

A directory marketplace named `superpowers-dev` points at the live checkout in
Claude Code. The installer deliberately refuses to replace it. Keep it if that
development behavior is wanted. To switch to the remote fork, review the current
registration and explicitly remove it before rerunning:

```sh
claude plugin marketplace list --json
claude plugin marketplace remove superpowers-dev
npx github:ktenman/superpowers
```

Claude's removal also uninstalls the plugin. For a conflicting Codex or Copilot
registration, the corresponding explicit migration commands are:

```sh
codex plugin remove superpowers@superpowers-dev
codex plugin marketplace remove superpowers-dev
# Or, for Copilot (also uninstalls plugins from that marketplace):
copilot plugin marketplace remove superpowers-dev --force
```

The installer prints these commands but does not run them. Removing only the
Codex marketplace leaves the cached plugin and its enabled setting behind.
An existing Git source without an explicit ref also needs migration so the
installer can verify which branch it will update.

Keep legacy `~/.codex/skills` symlinks until a fresh session using only the native
plugin discovers the skills and behaves as expected. Remove only links that you
have checked point into this checkout. The installer does not manage symlinks.
Use each harness's native plugin removal command to uninstall.

## Versioning and upstream syncs

Claude's plugin manifest and marketplace entry intentionally omit `version`.
Claude resolves the Git commit to a version, allowing fork changes between
upstream releases to update the installed cache. Keeping `6.4.1` in either
manifest made a real update report "already at the latest version" while its
installed files remained stale. A versionless two-commit fixture updated both
the version and the installed content on Claude Code 2.1.278.

The two Claude version fields are excluded from `.version-bump.json`; other
harness and package versions continue to follow upstream. Offline tests guard
this policy. The weekly sync can resolve conflicts limited to those three files
by keeping upstream's content minus the two versions and their registry entries.
It first verifies that the fork changed nothing else in those files. Other
conflicts, additional fork edits, deletions or unexpected formats still abort
the merge for review. New upstream metadata and registry entries are preserved.
`package.json`'s added `bin` can still require manual resolution; retain it when
reviewing upstream merges.

npx downloads the repository package, including skills and harness assets, not
just the installer script. Native CLIs fetch their own copies too. With npm
11.19.0, an unpinned GitHub npx package refreshed to a newer commit even when
`package.json`'s version was unchanged. npm's package cache and each harness's
plugin cache are separate; a fresh installer alone does not prove fresh skills.

## Bootstrap and verification

An installed/enabled plugin is not proof that its startup bootstrap ran. Codex
retains `"hooks": {}`: it exposes skill descriptions for the model to select,
without guaranteed SessionStart injection. This installer does not change skill
content or hook trust. Copilot CLI installation does not imply VS Code support.

Test in a fresh session with this exact prompt:

```text
Let's make a react todo list
```

`brainstorming` should load before application code is written. A plugin-only
Codex 0.155.1 / gpt-6-astra run loaded `using-superpowers` and `brainstorming` from
the plugin cache and asked about the intended use without writing code. This is
one observed run, not a reliability guarantee across models or compaction.

Copilot CLI 1.0.87 also injected the complete `using-superpowers` bootstrap into
its first model request in an isolated offline session. That test used a mock
provider: real-model brainstorming acceptance and hosted Copilot authentication
remain unverified. The isolated Claude setup had no login, so its authenticated
acceptance session remains unverified too.

Native command contracts were checked on macOS with Claude Code 2.1.278,
Codex 0.155.1, Copilot CLI 1.0.87, Node.js 24.21.0 and npm 11.19.0. This wrapper
targets macOS and Linux. Windows npm `.cmd` launchers are outside this change;
use the native installation instructions on Windows. Offline coverage runs with:

```sh
node --test tests/installer/test-install.mjs
bash tests/run-offline-tests.sh
```
