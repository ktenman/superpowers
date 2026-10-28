#!/usr/bin/env bash
# Run every test suite that needs no coding-agent CLI or API key. CI runs this
# on pull requests and after each upstream sync; run it locally before merging.
#
# Needs: node, python3 with pytest, jq, yq, graphviz, zip/unzip, and
# `npm ci --prefix tests/brainstorm-server` for the brainstorm-server suite.
# Run it from a real checkout: the codex packaging test rejects a git worktree.
#
# Left out on purpose:
# - the rest of tests/claude-code (run-skill-tests.sh and the tests that call
#   `claude`), tests/explicit-skill-requests and
#   tests/opencode/run-tests.sh --integration: they drive a real agent CLI.
# - tests/antigravity/test-plugin-manifest.sh: it expects the Claude manifest
#   version this fork omits (tests/installer/test-install.mjs asserts that).
# - tests/hooks/test-run-hook-cmd-windows.sh: Windows only.
# - tests/brainstorm-server/windows-lifecycle.test.sh: upstream keeps it out of
#   `npm test`; off Windows it skips its Windows cases and sleeps 150 seconds.
# - scripts/lint-shell.sh --all: red on upstream's baseline.
# The list is fixed and upstream adds tests without touching it: after a sync,
# check `git diff --name-status <old-tag> <new-tag> -- tests/` against it.
set -uo pipefail
cd "$(dirname "$0")/.."

# The codex packaging test compares DOS timestamps inside the archive and only
# passes in UTC, which is what CI runs in anyway.
export TZ=UTC
# The branding tests assert the default (opt-in) case; a telemetry opt-out
# inherited from the caller's shell, e.g. an agent session, would fail them.
unset DISABLE_TELEMETRY SUPERPOWERS_DISABLE_TELEMETRY CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC

suites=(
  "bash tests/hooks/test-session-start.sh"
  "bash tests/hooks/test-run-hook-direct-exec.sh"
  "bash tests/shell-lint/test-lint-shell.sh"
  "bash tests/codex/test-package-codex-plugin.sh"
  "bash tests/codex/test-marketplace-manifest.sh"
  "bash tests/codex-plugin-sync/test-sync-to-codex-plugin.sh"
  "bash tests/systematic-debugging/test-find-polluter.sh"
  "bash tests/diagnosing-superpowers/test-skill-structure.sh"
  "bash tests/claude-code/test-sdd-workspace.sh"
  "bash tests/claude-code/test-worktree-path-policy.sh"
  "bash tests/claude-code/test-executing-plans-scripts.sh"
  "bash tests/kimi/run-tests.sh"
  "bash tests/devin/test-devin-plugin.sh"
  "bash tests/antigravity/test-antigravity-tools.sh"
  "bash tests/antigravity/test-logo.sh"
  "bash tests/opencode/run-tests.sh"
  "bash tests/version-bump/test-bump-version.sh"
  "bash tests/writing-skills/test-render-graphs.sh"
  "bash tests/skill-size/test-skill-size.sh"
  "node --test tests/pi/test-pi-extension.mjs"
  "node --test tests/installer/test-install.mjs"
  "node --test tests/upstream-sync/test-sync-upstream.mjs"
  "npm test --prefix tests/brainstorm-server"
  "pytest -q tests/hermes"
  "scripts/bump-version.sh --check"
)

failed=()
for suite in "${suites[@]}"; do
  echo "=== $suite"
  if bash -c "$suite"; then
    echo "PASS  $suite"
  else
    echo "FAIL  $suite"
    failed+=("$suite")
  fi
  echo
done

echo "$((${#suites[@]} - ${#failed[@]}))/${#suites[@]} suites passed"
if [ "${#failed[@]}" -gt 0 ]; then
  printf 'FAIL  %s\n' "${failed[@]}"
  exit 1
fi
