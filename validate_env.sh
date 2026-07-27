#!/bin/bash
# Validation script for .env file
# This script checks if critical environment variables are set correctly

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Validating .env configuration..."
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ ERROR: .env file not found!"
    echo ""
    echo "Please create it from the template:"
    echo "  cp env.template .env"
    echo ""
    exit 1
fi

# Load environment variables
source .env 2>/dev/null || true

ERRORS=0
WARNINGS=0

# Check critical passwords
echo "Checking passwords..."
if [ "$POSTGRES_PASSWORD" = "your_secure_password_change_this" ]; then
    echo "  ❌ POSTGRES_PASSWORD is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

if [ "$DB_PASSWORD" = "your_secure_password_change_this" ]; then
    echo "  ❌ DB_PASSWORD is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

if [ "$JWT_POSTGRES_DATABASE_PASSWORD" = "your_secure_password_change_this" ]; then
    echo "  ❌ JWT_POSTGRES_DATABASE_PASSWORD is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

if [ "$DJANGO_SUPERUSER_PASSWORD" = "your_secure_password_change_this" ]; then
    echo "  ❌ DJANGO_SUPERUSER_PASSWORD is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

if [ "$OXIGRAPH_PASSWORD" = "your_oxigraph_password_change_this" ]; then
    echo "  ❌ OXIGRAPH_PASSWORD is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

if [ "$GRAPHDATABASE_PASSWORD" = "your_oxigraph_password_change_this" ]; then
    echo "  ❌ GRAPHDATABASE_PASSWORD is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

# Check password consistency
if [ "$POSTGRES_PASSWORD" != "$DB_PASSWORD" ]; then
    echo "  ❌ POSTGRES_PASSWORD and DB_PASSWORD do not match"
    ERRORS=$((ERRORS + 1))
fi

if [ "$POSTGRES_PASSWORD" != "$JWT_POSTGRES_DATABASE_PASSWORD" ]; then
    echo "  ❌ POSTGRES_PASSWORD and JWT_POSTGRES_DATABASE_PASSWORD do not match"
    ERRORS=$((ERRORS + 1))
fi

if [ "$OXIGRAPH_PASSWORD" != "$GRAPHDATABASE_PASSWORD" ]; then
    echo "  ❌ OXIGRAPH_PASSWORD and GRAPHDATABASE_PASSWORD do not match"
    ERRORS=$((ERRORS + 1))
fi

# Check JWT secret keys
if [ "$QUERY_SERVICE_JWT_SECRET_KEY" = "your-query-service-jwt-secret-key-change-this-in-production" ]; then
    echo "  ❌ QUERY_SERVICE_JWT_SECRET_KEY is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

if [ "$ML_SERVICE_JWT_SECRET_KEY" = "your-ml-service-jwt-secret-key-change-this-in-production" ]; then
    echo "  ❌ ML_SERVICE_JWT_SECRET_KEY is still set to default value"
    ERRORS=$((ERRORS + 1))
fi

# Check required environment variables
echo ""
echo "Checking required variables..."
REQUIRED_VARS=(
    "POSTGRES_USER"
    "POSTGRES_PASSWORD"
    "POSTGRES_DB"
    "DB_USER"
    "DB_PASSWORD"
    "DB_NAME"
    "JWT_POSTGRES_DATABASE_USER"
    "JWT_POSTGRES_DATABASE_PASSWORD"
    "JWT_POSTGRES_DATABASE_NAME"
    "QUERY_SERVICE_JWT_SECRET_KEY"
    "ML_SERVICE_JWT_SECRET_KEY"
)

for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "  ❌ $var is not set"
        ERRORS=$((ERRORS + 1))
    fi
done

# Check optional but recommended variables
echo ""
echo "Checking optional variables..."
OPTIONAL_VARS=(
    "MONGO_DB_URL"
    "OLLAMA_API_ENDPOINT"
    "GROBID_SERVER_URL_OR_EXTERNAL_SERVICE"
)

for var in "${OPTIONAL_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "  ⚠️  $var is not set (optional, some features may not work)"
        WARNINGS=$((WARNINGS + 1))
    fi
done

# Summary
echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo "✅ Validation passed!"
    if [ $WARNINGS -gt 0 ]; then
        echo "⚠️  $WARNINGS warnings (optional features may not work)"
    fi
    echo ""
    echo "You can now start the services:"
    echo "  ./start_services.sh"
    echo ""
    exit 0
else
    echo "❌ Validation failed with $ERRORS error(s)"
    if [ $WARNINGS -gt 0 ]; then
        echo "⚠️  $WARNINGS warning(s)"
    fi
    echo ""
    echo "Please fix the errors above before starting services."
    echo "Edit your .env file to update the configuration."
    echo ""
    exit 1
fi
