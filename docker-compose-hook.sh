#!/bin/bash
# -----------------------------------------------------------------------------
# Pre-hook Script for docker-compose
#
# This script is sourced by `docker-compose-wrapper.sh` and is responsible for
# automatically generating the `servers.json` configuration used by pgAdmin.
#
# Purpose:
#   Before docker-compose starts any services, this script ensures that
#   `servers.json` is up-to-date with the environment variables defined in `.env`.
#   This prevents pgAdmin from loading outdated connection settings.
#
# Behavior:
#   • Checks if the pgAdmin generator script exists:
#       pgadmin-init/generate-servers-json.sh
#
#   • If present, it compares timestamps between:
#       - pgadmin-init/servers.json
#       - .env
#     The file is regenerated only if:
#       - servers.json does not exist, OR
#       - servers.json is older than the .env file
#
#   • When regeneration is needed:
#       - Executes the generator script
#       - Suppresses script output for cleanliness
#       - Displays user-friendly status messages
#
# Notes:
#   • This script does *not* run docker-compose by itself—it's purely a pre-hook.
#   • It is safe to run repeatedly; regeneration happens only when required.
#
# -----------------------------------------------------------------------------
if [ -f "pgadmin-init/generate-servers-json.sh" ]; then
    # Only generate if file doesn't exist or is older than .env
    if [ ! -f "pgadmin-init/servers.json" ] || [ "pgadmin-init/servers.json" -ot ".env" ]; then
        echo "🔄 Auto-generating servers.json from environment variables..."
        bash pgadmin-init/generate-servers-json.sh pgadmin-init > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo "✅ servers.json generated successfully"
        fi
    fi
fi

