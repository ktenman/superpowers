#!/usr/bin/env bash
# Fork-only regression test for hooks/run-hook.cmd. The wrapper has no shebang,
# so a harness that execs it without a shell gets libc's sh fallback, and on
# macOS that fallback keeps the caller's argv[0]. Bash derives $BASH from
# argv[0], so $BASH names the wrapper itself. The wrapper must not exec that:
# it would re-run itself forever instead of dispatching the hook.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "test-run-hook-direct-exec: starting run-hook.cmd with itself as argv[0]"

# exec -a reproduces that start on any platform. The CPU limit turns a
# regression into a failure (exit 152 or 137) instead of a runaway process.
# The relative spelling is the one hooks-cursor.json uses: bash makes $BASH
# absolute, so $BASH and $0 then name the same file with different strings.
cd "$REPO_ROOT"
for wrapper in "$REPO_ROOT/hooks/run-hook.cmd" ./hooks/run-hook.cmd; do
  output="$(ulimit -t 5; exec -a "$wrapper" "$BASH" "$wrapper" session-start 2>&1)" \
    || fail "run-hook.cmd started as $wrapper exited $?: ${output:-no output}"
  grep -q 'You have superpowers' <<<"$output" \
    || fail "run-hook.cmd started as $wrapper did not dispatch session-start"
done

echo "PASS: run-hook.cmd dispatches session-start when \$BASH names the wrapper"
