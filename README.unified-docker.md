# Unified Docker Deployment

This Dockerfile deploys the following BrainKB backend services:
- **APItokenmanager** (Django) - Port 8000
- **query_service** (FastAPI) - Port 8010
- **ml_service** (FastAPI) - Port 8007
- **usermanagement_service** (FastAPI) - Port 8004
- **oxigraph** (SPARQL Database) - Port 7878

**Services NOT included in this unified deployment (deploy separately):**
- **brainkb-ui** - The UI is not included. See [SETUP_UI.md](SETUP_UI.md) for UI deployment instructions.
- **chat_service** - Deploy separately using `chat_service/docker-compose-prod.yml` or `chat_service/docker-compose-dev.yml`.

## Quick Start with Docker Compose (Recommended)

The easiest way to deploy is using the provided `start_services.sh` wrapper script:

### 1. Create Environment File

Create a `.env` file in the project root with your configuration:

```bash
# Copy the template and edit as needed
cp env.template .env
# Edit .env with your actual values
nano .env  # or use your preferred editor
```

**Important:** Update at minimum these values in `.env`:
- `JWT_POSTGRES_DATABASE_PASSWORD` - Database password (primary PostgreSQL configuration)
- `DB_PASSWORD` - Should match JWT_POSTGRES_DATABASE_PASSWORD (for Django APItokenmanager)
- `DJANGO_SUPERUSER_PASSWORD` - Admin password for Django
- `BRAINYPEDIA_APITOKEN_MANAGER_SECRET_KEY` - Django secret key
- `*_SERVICE_JWT_SECRET_KEY` - Service-specific JWT signing secrets (one per service)
- `OXIGRAPH_PASSWORD` - Oxigraph authentication password
- `OLLAMA_MODEL` - Ollama model to use (default: nomic-embed-text)
- `NEXTAUTH_SECRET` - NextAuth.js secret for UI
- `NEXT_PUBLIC_*` - UI API endpoint URLs (adjust based on your deployment)

### 2. Start All Services

**Recommended: Use the wrapper script (includes Ollama setup and auto-configuration):**
```bash
./start_services.sh
```

This will automatically:
- ✅ Detect GPU availability and set up Ollama (CPU or GPU mode)
- ✅ Load the Ollama model specified in `OLLAMA_MODEL` from `.env`
- ✅ Auto-generate pgAdmin servers.json
- ✅ Start PostgreSQL database
- ✅ Build and start the unified BrainKB container
- ✅ Set up networking and volumes
- ✅ Configure all environment variables

**Alternative: Manual docker-compose (without Ollama auto-setup):**
```bash
docker-compose -f docker-compose.unified.yml up -d
```

### 3. Managing Services

The `start_services.sh` script provides flexible service management:

#### Start/Stop All Services
```bash
# Start all services
./start_services.sh up -d

# Stop all services
./start_services.sh down

# Restart all services
./start_services.sh restart
```

#### Control Individual Containers
```bash
# Start/stop specific containers
./start_services.sh brainkb-unified up
./start_services.sh postgres down
./start_services.sh pgadmin restart
```

#### Control Individual Microservices (inside brainkb-unified)
```bash
# Restart only query service (doesn't affect other services)
./start_services.sh query-service restart

# Restart only ML service
./start_services.sh ml-service restart

# Restart only API token manager
./start_services.sh api-token-manager restart

# Check status of a microservice
./start_services.sh query-service status

# View logs of a microservice
./start_services.sh query-service logs
```

**Available microservices:**
- `query-service` - Query Service (port 8010)
- `ml-service` - ML Service (port 8007)
- `api-token-manager` - API Token Manager (port 8000)
- `usermanagement-service` - User Management Service (port 8004)

#### Ollama Management
```bash
# Start Ollama (auto-detects GPU/CPU)
./start_services.sh ollama up

# Stop Ollama
./start_services.sh ollama down

# Restart Ollama
./start_services.sh ollama restart
```

### 4. View Logs

```bash
# All services
./start_services.sh logs -f

# Specific container
./start_services.sh logs -f brainkb-unified

# Specific microservice (inside brainkb-unified)
./start_services.sh query-service logs
```

### 5. Stop Services

```bash
# Stop all services
./start_services.sh down

# Stop specific container
./start_services.sh brainkb-unified down
```

### 5. Access pgAdmin

pgAdmin is included by default and will start automatically.

Access pgAdmin at `http://localhost:5051` (default port, configurable via `PGADMIN_PORT` in `.env`)

**Default credentials:**
- Email: `admin@brainkb.org` (set via `PGADMIN_DEFAULT_EMAIL` in `.env`)
- Password: `admin` (set via `PGADMIN_DEFAULT_PASSWORD` in `.env`)

**Automatic PostgreSQL Server Registration:**
The PostgreSQL server is automatically configured when pgAdmin starts! After logging in, you should see **"BrainKB PostgreSQL"** (or your `PGADMIN_SERVER_NAME` value) in the left panel under "Servers". Simply click on it to connect.

The connection uses:
- Host: `postgres` (Docker service name)
- Port: `5432`
- Database: Your `JWT_POSTGRES_DATABASE_NAME` value (default: `brainkb`)
- Username: Your `JWT_POSTGRES_DATABASE_USER` value (default: `postgres`)
- Password: Automatically configured from `JWT_POSTGRES_DATABASE_PASSWORD` in your `.env` file

See [PGADMIN_SETUP.md](PGADMIN_SETUP.md) for more details.

## Manual Docker Build and Run

### Building the Image

```bash
docker build -f Dockerfile.unified -t brainkb-unified:latest .
```

### Running the Container

### Basic Usage

```bash
docker run -d \
  --name brainkb-unified \
  -p 8000:8000 \
  -p 8004:8004 \
  -p 8007:8007 \
  -p 8010:8010 \
  -v /path/to/data:/data \
  -e DB_NAME=your_db_name \
  -e DB_USER=your_db_user \
  -e DB_PASSWORD=your_db_password \
  -e DB_HOST=your_db_host \
  -e DB_PORT=5432 \
  -e OXIGRAPH_USER=admin \
  -e OXIGRAPH_PASSWORD=admin \
  brainkb-unified:latest
```

### Environment Variables

#### Database Configuration (for APItokenmanager)
- `DB_NAME` - PostgreSQL database name
- `DB_USER` - PostgreSQL username
- `DB_PASSWORD` - PostgreSQL password
- `DB_HOST` - PostgreSQL host (default: localhost)
- `DB_PORT` - PostgreSQL port (default: 5432)

#### Oxigraph Authentication
- `OXIGRAPH_USER` - Username for oxigraph SPARQL endpoint
- `OXIGRAPH_PASSWORD` - Password for oxigraph SPARQL endpoint

#### Django Superuser (Optional)
- `DJANGO_SUPERUSER_USERNAME` - Django admin username
- `DJANGO_SUPERUSER_EMAIL` - Django admin email
- `DJANGO_SUPERUSER_PASSWORD` - Django admin password

### Service Endpoints

Services are accessible directly on their respective ports:

- **API Token Manager**: `http://localhost:8000/`
- **Query Service**: `http://localhost:8010/`
- **ML Service**: `http://localhost:8007/`
- **User Management Service**: `http://localhost:8004/`
- **Oxigraph SPARQL**: `http://localhost:7878/` (password protected)
- **pgAdmin**: `http://localhost:5051/`
- **Ollama**: `http://localhost:11434/` (if started separately)

**Note:** 
- UI should be deployed separately and configured to point to these backend endpoints
- All services are accessible directly on their configured ports
- pgAdmin starts automatically with the deployment
- Ollama is set up automatically by `start_services.sh` (GPU/CPU auto-detected)

### Data Persistence

Mount a volume for oxigraph data storage:
```bash
-v /path/to/oxigraph-data:/data
```

### Viewing Logs

**Using start_services.sh (recommended):**
```bash
# All services
./start_services.sh logs -f

# Specific microservice
./start_services.sh query-service logs
./start_services.sh ml-service logs
./start_services.sh api-token-manager logs
```

**Direct docker commands:**
```bash
# All services
docker logs brainkb-unified

# Individual service logs (inside container)
docker exec brainkb-unified tail -f /var/log/supervisor/api_tokenmanager.out.log
docker exec brainkb-unified tail -f /var/log/supervisor/query_service.out.log
docker exec brainkb-unified tail -f /var/log/supervisor/ml_service.out.log
docker exec brainkb-unified tail -f /var/log/supervisor/usermanagement_service.out.log
docker exec brainkb-unified tail -f /var/log/supervisor/oxigraph.out.log
```

### Managing Services

**Using start_services.sh (recommended):**
```bash
# Restart individual microservices (fast, no downtime for other services)
./start_services.sh query-service restart
./start_services.sh ml-service restart
./start_services.sh api-token-manager restart
./start_services.sh usermanagement-service restart

# Check status
./start_services.sh query-service status

# Start/stop individual microservices
./start_services.sh query-service start
./start_services.sh query-service stop
```

**Direct supervisor commands:**
```bash
# View all service statuses
docker exec -it brainkb-unified supervisorctl status

# Restart individual services
docker exec -it brainkb-unified supervisorctl restart api_tokenmanager
docker exec -it brainkb-unified supervisorctl restart query_service
docker exec -it brainkb-unified supervisorctl restart ml_service
docker exec -it brainkb-unified supervisorctl restart usermanagement_service
docker exec -it brainkb-unified supervisorctl restart oxigraph
```

### Ollama Configuration

Ollama is automatically set up by `start_services.sh` with the following features:

- **Automatic GPU Detection**: Detects NVIDIA GPU and uses GPU acceleration if available
- **CPU Fallback**: Falls back to CPU mode if GPU is not available
- **Model Loading**: Automatically loads the model specified in `OLLAMA_MODEL` from `.env`
- **Persistent Storage**: Uses Docker volume for model storage

**Configuration in `.env`:**
```bash
# Ollama model to use
OLLAMA_MODEL=nomic-embed-text

# Ollama port (default: 11434)
OLLAMA_PORT=11434

# Ollama API endpoint (for services in Docker)
OLLAMA_API_ENDPOINT=http://host.docker.internal:11434
```

**Manual Ollama Management:**
```bash
# Start Ollama
./start_services.sh ollama up

# Stop Ollama
./start_services.sh ollama down

# Check Ollama status
docker ps | grep ollama
docker exec ollama ollama list
```

**GPU Requirements:**
- For GPU support, install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- The script automatically detects GPU availability and configures accordingly

## Notes

1. **Oxigraph**: The oxigraph binary is extracted from the official Docker image. If it's not available for your architecture, you may need to run oxigraph in a separate container.

2. **Database**: Ensure PostgreSQL is running and accessible. The APItokenmanager service will run migrations automatically on startup.

3. **Static Files**: Django static files are collected automatically on startup.

4. **Resource Requirements**: This unified container runs multiple services. Ensure adequate CPU and memory resources:
   - Minimum: 4 CPU cores, 8GB RAM
   - Recommended: 8 CPU cores, 16GB RAM

## Troubleshooting

### Services not starting
Check supervisor logs:
```bash
docker exec brainkb-unified cat /var/log/supervisor/supervisord.log
```

### Database connection issues

1. **Verify all passwords match in `.env`:**
   - `JWT_POSTGRES_DATABASE_PASSWORD` must match:
     - `DB_PASSWORD` (for Django APItokenmanager)
   - All should be the same value!

2. **Test database connection:**
   ```bash
   docker exec brainkb-unified psql -h postgres -U postgres -d brainkb
   # Enter password when prompted
   ```

3. **Check database logs:**
   ```bash
   docker logs brainkb-postgres
   ```

4. **Verify services can reach postgres:**
   ```bash
   docker exec brainkb-unified ping -c 3 postgres
   ```

### API Token Manager login issues

1. **Verify SECRET_KEY is set:**
   ```bash
   docker exec brainkb-unified env | grep BRAINYPEDIA_APITOKEN_MANAGER_SECRET_KEY
   ```
   If empty, add it to your `.env` file. Generate one with:
   ```bash
   python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
   ```

2. **Check if superuser was created:**
   ```bash
   docker exec brainkb-unified python /app/APItokenmanager/manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); print('Superusers:', list(User.objects.filter(is_superuser=True).values_list('username', flat=True)))"
   ```

3. **Verify superuser credentials in .env:**
   ```bash
   docker exec brainkb-unified env | grep DJANGO_SUPERUSER
   ```
   Make sure `DJANGO_SUPERUSER_PASSWORD` is set (not the placeholder value).

4. **Create superuser manually if needed:**
   ```bash
   docker exec -it brainkb-unified python /app/APItokenmanager/manage.py createsuperuser
   ```

5. **Check Django logs:**
   ```bash
   docker exec brainkb-unified tail -f /var/log/supervisor/api_tokenmanager.out.log
   docker exec brainkb-unified tail -f /var/log/supervisor/api_tokenmanager.err.log
   ```

6. **Test database connection:**
   ```bash
   docker exec brainkb-unified python /app/APItokenmanager/manage.py dbshell
   ```

See [TROUBLESHOOTING_API_TOKEN_MANAGER.md](TROUBLESHOOTING_API_TOKEN_MANAGER.md) for detailed troubleshooting steps.

### Query Service not working (port 8010)

1. **Check if service is running:**
   ```bash
   docker exec brainkb-unified supervisorctl status query_service
   ```

2. **Check query service logs:**
   ```bash
   docker exec brainkb-unified tail -f /var/log/supervisor/query_service.out.log
   docker exec brainkb-unified tail -f /var/log/supervisor/query_service.err.log
   ```

3. **Verify database connection:**
   - Check that `DB_PASSWORD` matches `JWT_POSTGRES_DATABASE_PASSWORD` in `.env`
   - Check that `JWT_POSTGRES_DATABASE_HOST_URL=postgres` (Docker service name)

4. **Test query service directly:**
   ```bash
   curl http://localhost:8010/
   ```

### Testing Service Accessibility

After starting services, test if they're accessible:

```bash
# Check if services are running
docker-compose -f docker-compose.unified.yml ps

# Test API Token Manager
curl http://localhost:8000/

# Test Query Service
curl http://localhost:8010/

# Test ML Service
curl http://localhost:8007/

# Test User Management Service
curl http://localhost:8004/


# Test Oxigraph (password protected via HTTP Basic Auth)
# Use credentials from OXIGRAPH_USER and OXIGRAPH_PASSWORD in .env
curl -u admin:pwdoxigraph http://localhost:7878/

# Check service logs if not accessible
docker logs brainkb-unified
docker exec brainkb-unified supervisorctl status
```

### Services not accessible

1. **Check if services are running:**
   ```bash
   docker exec brainkb-unified supervisorctl status
   ```

2. **Check service logs:**
   ```bash
   docker exec brainkb-unified tail -f /var/log/supervisor/query_service.out.log
   docker exec brainkb-unified tail -f /var/log/supervisor/api_tokenmanager.out.log
   ```

3. **Verify ports are exposed:**
   ```bash
   docker-compose -f docker-compose.unified.yml ps
   # Should show all ports mapped
   ```

4. **Check if services are binding to 0.0.0.0:**
   ```bash
   docker exec brainkb-unified netstat -tlnp
   # Should show services listening on 0.0.0.0:PORT
   ```

### pgAdmin not accessible

pgAdmin should start automatically. If it's not accessible:

1. **Check if pgAdmin container is running:**
   ```bash
   docker-compose -f docker-compose.unified.yml ps
   ```

2. **Check pgAdmin logs:**
   ```bash
   docker logs brainkb-pgadmin
   ```

3. **Verify port is not in use:**
   ```bash
   # Check if port 5051 is already in use
   lsof -i :5051
   ```

4. **Access at:** `http://localhost:5051` (or your `PGADMIN_PORT` value)

## Docker Compose Configuration

The `docker-compose.unified.yml` file includes:

### Services

1. **postgres**: PostgreSQL database for APItokenmanager and JWT services
2. **brainkb-unified**: Main container with all BrainKB services (API Token Manager, Query Service, ML Service, User Management Service)
3. **oxigraph**: SPARQL Database (internal, not directly exposed)
4. **oxigraph-nginx**: Nginx reverse proxy with HTTP Basic Authentication for Oxigraph (password protected)
5. **pgadmin**: PostgreSQL Admin Interface (starts automatically)

### Volumes

- `postgres_data`: Persistent storage for PostgreSQL
- `oxigraph_data`: Persistent storage for Oxigraph SPARQL database
- `pgadmin_data`: Persistent storage for pgAdmin (if enabled)

### Networks

- `brainkb-network`: Bridge network connecting all services

### Environment Variables

All environment variables are loaded from the `.env` file in the project root. The `env_file` directive in docker-compose automatically loads all variables from `.env` into the container.

**Key Variables to Configure:**

- **Database**: `JWT_POSTGRES_DATABASE_USER`, `JWT_POSTGRES_DATABASE_PASSWORD`, `JWT_POSTGRES_DATABASE_NAME`
- **Django**: `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `BRAINYPEDIA_APITOKEN_MANAGER_SECRET_KEY`
- **JWT**: `*_SERVICE_JWT_SECRET_KEY` (service-specific keys), `JWT_POSTGRES_*` (all JWT-related variables)
- **Oxigraph**: `OXIGRAPH_USER`, `OXIGRAPH_PASSWORD`
- **Ports**: `API_TOKEN_PORT`, `QUERY_SERVICE_PORT`, `ML_SERVICE_PORT`, `USERMANAGEMENT_SERVICE_PORT`, `OXIGRAPH_PORT`, `PGADMIN_PORT`
- **User Management OAuth**: `USERMANAGEMENT_SERVICE_JWT_SECRET_KEY`, `USERMANAGEMENT_PUBLIC_BASE_URL`, `USERMANAGEMENT_FRONTEND_CALLBACK_URL`, `USERMANAGEMENT_OAUTH_TOKEN_ENC_KEY`, `USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS`, `GITHUB_CLIENT_ID/SECRET`, `ORCID_CLIENT_ID/SECRET`, `GLOBUS_CLIENT_ID/SECRET`
- **Ollama**: `OLLAMA_MODEL`, `OLLAMA_PORT`, `OLLAMA_API_ENDPOINT`
- **ML Service**: `MONGO_DB_URL`, `WEAVIATE_*`, etc.
- **Query Service**: `GRAPHDATABASE_*`, `RAPID_RELEASE_FILE`

See `env.template` for the complete list of all available environment variables with descriptions.

### Health Checks

- PostgreSQL has a health check to ensure it's ready before starting the unified container
- The unified container has a health check on the API Token Manager endpoint

### Scaling

To run multiple instances or scale specific services, modify the compose file or use:

```bash
docker-compose -f docker-compose.unified.yml up -d --scale brainkb-unified=2
```

Note: Only scale if you have a load balancer in front, as port conflicts will occur.

