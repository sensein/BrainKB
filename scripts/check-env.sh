#!/bin/bash
# -----------------------------------------------------------------------------
# check-env.sh
#
# Detect env-key drift between env.template (the source of truth for what
# config the stack expects) and .env (the live values).
#
# Compares ONLY KEY NAMES, not values — values diverge intentionally
# (secrets, host-specific URLs, etc.). The check is one-directional by
# default: every key in the template must exist in .env, but extras in .env
# are reported as a non-fatal note.
#
# Usage:
#   ./scripts/check-env.sh                    # default paths: <repo>/env.template, <repo>/.env
#   ./scripts/check-env.sh TEMPLATE ENVFILE   # explicit paths
#
# Exit codes:
#   0  no drift (every template key exists in .env)
#   1  drift detected (one or more template keys missing in .env)
#   2  invocation error (template or .env file missing)
#
# Wiring suggestions:
#   - Add a call near the top of start_services.sh so deployments fail loudly
#     when the live .env has fallen behind the template.
#   - Add a pre-commit hook that runs it whenever env.template changes.
# -----------------------------------------------------------------------------

set -euo pipefail

# Resolve repo root from this script's own location so relative invocations
# (e.g. `bash scripts/check-env.sh` from any cwd) still find env.template.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

TEMPLATE="${1:-$REPO_ROOT/env.template}"
ENV_FILE="${2:-$REPO_ROOT/.env}"

if [[ ! -f "$TEMPLATE" ]]; then
    echo "check-env: template not found: $TEMPLATE" >&2
    exit 2
fi
if [[ ! -f "$ENV_FILE" ]]; then
    echo "check-env: env file not found: $ENV_FILE" >&2
    exit 2
fi

if [[ -t 1 ]]; then
    RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; GREEN=$'\033[0;32m'; BOLD=$'\033[1m'; RESET=$'\033[0m'
else
    RED=''; YELLOW=''; GREEN=''; BOLD=''; RESET=''
fi

# Extract dotenv KEY names from a file. Accepts:
#   KEY=value
#   export KEY=value
#   KEY="value with spaces"
#   leading whitespace, # comments, blanks, all ignored
extract_keys() {
    grep -E '^[[:space:]]*(export[[:space:]]+)?[A-Z_][A-Z0-9_]*=' "$1" \
        | sed -E 's/^[[:space:]]*(export[[:space:]]+)?([A-Z_][A-Z0-9_]*)=.*/\2/' \
        | sort -u
}

template_keys=$(extract_keys "$TEMPLATE")
env_keys=$(extract_keys "$ENV_FILE")

missing_in_env=$(comm -23 <(echo "$template_keys") <(echo "$env_keys"))
extra_in_env=$(comm -13 <(echo "$template_keys") <(echo "$env_keys"))

failed=0
template_count=$(echo "$template_keys" | grep -c . || true)

if [[ -n "$missing_in_env" ]]; then
    failed=1
    echo "${BOLD}${RED}env drift:${RESET} keys present in ${TEMPLATE#$REPO_ROOT/} but missing from ${ENV_FILE#$REPO_ROOT/}"
    while IFS= read -r k; do
        echo "  ${RED}-${RESET} $k"
    done <<< "$missing_in_env"
fi

if [[ -n "$extra_in_env" ]]; then
    echo "${YELLOW}note:${RESET} keys in ${ENV_FILE#$REPO_ROOT/} but not in ${TEMPLATE#$REPO_ROOT/} (probably fine; consider adding to template):"
    while IFS= read -r k; do
        echo "  ${YELLOW}+${RESET} $k"
    done <<< "$extra_in_env"
fi

if [[ "$failed" -eq 1 ]]; then
    echo
    echo "fix by adding the missing keys (with appropriate values) to ${BOLD}${ENV_FILE#$REPO_ROOT/}${RESET}."
    echo "values can be copied from ${TEMPLATE#$REPO_ROOT/}, but secrets should be regenerated, not reused."
    exit 1
fi

if [[ -z "$extra_in_env" ]]; then
    echo "${GREEN}env keys aligned${RESET} (${template_count} keys checked, no drift)"
else
    echo "${GREEN}all template keys present${RESET} (${template_count} checked); see notes above for extras"
fi
exit 0
