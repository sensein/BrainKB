#!/bin/bash
# The following JSON defines a preconfigured PostgreSQL server entry for pgAdmin.
# It is included in servers.json so that pgAdmin automatically displays this server
# on first login. Users only need to enter the password once, instead of manually
# creating the connection. Update the fields (Name, MaintenanceDB, Username, etc.)
# to match your PostgreSQL setup.

# {
#   "Servers": {
#     "1": {
#       "Name": "Your PostgreSQL Server Name",
#       "Group": "Servers",
#       "Host": "postgres",
#       "Port": 5432,
#       "MaintenanceDB": "dbname",
#       "Username": "username",
#       "Password": "password",
#       "SSLMode": "prefer",
#       "Comment": "BrainKB PostgreSQL Database"
#     }
#   }
# }


# Get environment variables (with defaults)
PGADMIN_EMAIL="${PGADMIN_DEFAULT_EMAIL:-admin@brainkb.org}"
POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_DB="${POSTGRES_DB:-brainkb}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
SERVER_NAME="${PGADMIN_SERVER_NAME:-BrainKB PostgreSQL}"

# Output directory
# If no argument provided, use script's directory (for host usage)
# If argument provided, use that path (for container usage)
if [ -z "$1" ]; then
    # Running on host - output to script's directory
    OUTPUT_DIR="$(cd "$(dirname "$0")" && pwd)"
else
    # Running in container - use provided path
    OUTPUT_DIR="$1"
fi
SERVERS_JSON="${OUTPUT_DIR}/servers.json"

# Remove if it's a directory (shouldn't happen, but just in case)
if [ -d "$SERVERS_JSON" ]; then
    echo "Warning: ${SERVERS_JSON} is a directory, removing it..."
    rm -rf "$SERVERS_JSON"
fi

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Generate servers.json
cat > "$SERVERS_JSON" << EOF
{
  "Servers": {
    "1": {
      "Name": "${SERVER_NAME}",
      "Group": "Servers",
      "Host": "${POSTGRES_HOST}",
      "Port": ${POSTGRES_PORT},
      "MaintenanceDB": "${POSTGRES_DB}",
      "Username": "${POSTGRES_USER}",
      "Password": "${POSTGRES_PASSWORD}",
      "SSLMode": "prefer",
      "Comment": "BrainKB PostgreSQL Database"
    }
  }
}
EOF

echo "Generated ${SERVERS_JSON}"
echo ""
echo "Server configuration:"
echo "  Name: ${SERVER_NAME}"
echo "  Host: ${POSTGRES_HOST}"
echo "  Port: ${POSTGRES_PORT}"
echo "  Database: ${POSTGRES_DB}"
echo "  Username: ${POSTGRES_USER}"

