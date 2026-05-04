#!/bin/bash
set -e

# Note: Oxigraph runs as a separate service in docker-compose

# Ensure supervisor socket directory exists and is writable
mkdir -p /var/run
chmod 755 /var/run

# Wait for PostgreSQL to be ready
# Use JWT_POSTGRES_DATABASE_USER if available, otherwise fall back to DB_USER
# This ensures we use the same user that PostgreSQL was initialized with
PG_USER="${JWT_POSTGRES_DATABASE_USER:-${DB_USER:-postgres}}"
PG_PASSWORD="${JWT_POSTGRES_DATABASE_PASSWORD:-${DB_PASSWORD}}"
PG_HOST="${JWT_POSTGRES_DATABASE_HOST_URL:-${DB_HOST:-postgres}}"
PG_DB="${JWT_POSTGRES_DATABASE_NAME:-${DB_NAME:-brainkb}}"

echo "Waiting for PostgreSQL to be ready..."
echo "Connecting as user: ${PG_USER} to database: ${PG_DB} on host: ${PG_HOST}"
until PGPASSWORD="$PG_PASSWORD" psql -h "$PG_HOST" -U "$PG_USER" -d "$PG_DB" -c '\q' 2>/dev/null; do
    echo "PostgreSQL is unavailable - sleeping"
    sleep 2
done
echo "PostgreSQL is ready!"

# Note: Oxigraph is optional - services will handle connection failures gracefully
# No need to wait for it here - services will retry when needed

# Run Django migrations for APItokenmanager if needed
cd /app/APItokenmanager
if [ -f .env ] || [ -n "$DB_NAME" ]; then
    echo "Running Django migrations..."
    python manage.py makemigrations || true
    python manage.py migrate || true
    python manage.py collectstatic --noinput || true

    # Create superuser if credentials are provided and user doesn't exist
    if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
        echo "Creating Django superuser..."
        export DJANGO_SUPERUSER_USERNAME DJANGO_SUPERUSER_EMAIL DJANGO_SUPERUSER_PASSWORD
        python manage.py shell << 'PYTHON_SCRIPT' || true
import os
from django.contrib.auth import get_user_model
User = get_user_model()
username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
if username and email and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, email, password)
        print(f'Superuser {username} created successfully')
    else:
        print(f'Superuser {username} already exists')
else:
    print('Error: Missing superuser credentials in environment')
PYTHON_SCRIPT
    else
        echo "Warning: DJANGO_SUPERUSER credentials not provided. Superuser not created."
        echo "You can create one manually with: python manage.py createsuperuser"
    fi

    echo "Django migrations completed"
fi

# Start supervisor
echo "Starting all services..."
# Use our config file that includes socket configuration
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
