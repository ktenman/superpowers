#!/usr/bin/env bash
#
# install.sh — install or resync this working copy as a Claude Code plugin.
#
# Usage:
#   scripts/install.sh          Register the marketplace if needed, then install/update
#   scripts/install.sh --check  Report current state, change nothing
#
# Claude Code copies directory-sourced plugins into a cache, so local edits are
# not live. Run this after changing skills to refresh that cache, then restart.
set -euo pipefail

# -P everywhere: comparing a logical path against the physical one Claude Code
# records makes the path guard below fire on a symlinked checkout.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd -P)"

usage() {
  sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//'
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_tool() {
  command -v "$1" >/dev/null 2>&1 || die "required tool '$1' is not on PATH"
}

check_only=false
case "${1-}" in
  --check)
    check_only=true
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  "") ;;
  *)
    die "unknown option: $1"
    ;;
esac

require_tool claude
require_tool jq

MARKETPLACE_JSON="$REPO_ROOT/.claude-plugin/marketplace.json"
PLUGIN_JSON="$REPO_ROOT/.claude-plugin/plugin.json"
[[ -f "$MARKETPLACE_JSON" ]] || die "not a plugin repo: no $MARKETPLACE_JSON"
[[ -f "$PLUGIN_JSON" ]] || die "not a plugin repo: no $PLUGIN_JSON"

# Read the names rather than hardcoding, so an upstream rename does not break this.
MARKETPLACE="$(jq -r '.name' "$MARKETPLACE_JSON")"
PLUGIN="$(jq -r '.name' "$PLUGIN_JSON")"
VERSION="$(jq -r '.version' "$PLUGIN_JSON")"
ID="$PLUGIN@$MARKETPLACE"

# Resolve to a physical path so the guard compares like with like. Portable to
# bash 3.2 / macOS, where realpath is not guaranteed.
abspath() {
  [[ -d "$1" ]] || {
    printf '%s' "$1"
    return 0
  }
  (cd "$1" && pwd -P)
}

registered_path() {
  local path
  path="$(claude plugin marketplace list --json \
    | jq -r --arg n "$MARKETPLACE" '.[] | select(.name == $n) | .installLocation')"
  # An `if` with no else exits 0, so an unregistered marketplace does not trip set -e.
  if [[ -n "$path" ]]; then
    abspath "$path"
  fi
}

# Prints "" when not installed. Booleans survive as "true"/"false" -- do not
# swap this for `// empty`, which swallows a false `enabled`.
installed_field() {
  claude plugin list --json \
    | jq -r --arg id "$ID" --arg f "$1" \
      'map(select(.id == $id and .scope == "user"))
       | if length == 0 then "" else (.[0][$f] | tostring) end'
}

report() {
  local market_path installed_version enabled
  market_path="$(registered_path)"
  installed_version="$(installed_field version)"
  enabled="$(installed_field enabled)"

  echo "repo         $REPO_ROOT ($PLUGIN v$VERSION)"
  echo "marketplace  ${market_path:-not registered}"
  echo "installed    ${installed_version:-not installed}"
  echo "enabled      ${enabled:-n/a}"

  if [[ -n "$market_path" && "$market_path" != "$REPO_ROOT" ]]; then
    die "marketplace '$MARKETPLACE' points at $market_path, not this repo.
  Remove it first: claude plugin marketplace remove $MARKETPLACE"
  fi

  if [[ "$enabled" == "false" ]]; then
    echo
    echo "warning: $ID is installed but DISABLED -- skills will not load."
    echo "  Enable it: claude plugin enable $ID"
  fi
}

report
if [[ "$check_only" == true ]]; then
  exit 0
fi

echo
if [[ -z "$(registered_path)" ]]; then
  claude plugin marketplace add "$REPO_ROOT"
else
  claude plugin marketplace update "$MARKETPLACE"
fi

if [[ -z "$(installed_field version)" ]]; then
  claude plugin install "$ID"
else
  claude plugin update "$ID"
fi

echo
echo "now at v$(installed_field version) -- restart Claude Code to load it."
