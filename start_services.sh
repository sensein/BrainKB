#!/bin/bash
# Wrapper script for docker-compose that auto-generates servers.json.
#
# Usage:
#   ./start_services.sh                          # Equivalent to: docker compose -f docker-compose.unified.yml up -d
#   ./start_services.sh down                     # Equivalent to: docker compose -f docker-compose.unified.yml down
#   ./start_services.sh logs -f                  # Equivalent to: docker compose -f docker-compose.unified.yml logs -f
#
# Optional: Make it your default docker-compose command by adding this alias
# to your ~/.bashrc or ~/.zshrc:
#   alias docker-compose='path/to/BrainKB/start_services.sh'


# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Source the hook script if it exists
if [ -f ".docker-compose-hook.sh" ]; then
    source .docker-compose-hook.sh
fi

# If no arguments provided, default to "up -d"
if [ $# -eq 0 ]; then
    set -- up
fi

# Check if -f flag is provided, if not, default to docker-compose.unified.yml
HAS_FILE_FLAG=false
for arg in "$@"; do
    if [ "$arg" = "-f" ] || [ "$arg" = "--file" ]; then
        HAS_FILE_FLAG=true
        break
    fi
done

# If no -f flag, prepend -f docker-compose.unified.yml
if [ "$HAS_FILE_FLAG" = false ]; then
    set -- -f docker-compose.unified.yml "$@"
fi

# Detect which docker-compose command is available
# Try docker compose (plugin, newer) first, then docker-compose (standalone, older)
if docker compose version >/dev/null 2>&1; then
    # Use docker compose (plugin version)
    exec docker compose "$@"
elif command -v docker-compose >/dev/null 2>&1; then
    # Use docker-compose (standalone version)
    exec docker-compose "$@"
else
    echo " Error: Neither 'docker compose' nor 'docker-compose' found in PATH"
    echo " Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

