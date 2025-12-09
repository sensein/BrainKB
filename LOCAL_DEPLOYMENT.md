# BrainKB Local Deployment Guide

This guide provides step-by-step instructions for deploying BrainKB locally on macOS, Windows, and Linux.

## Table of Contents
- [Prerequisites](#prerequisites)
  - [macOS Setup](#macos-setup)
  - [Windows Setup](#windows-setup)
  - [Linux Setup](#linux-setup)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Common Requirements (All Platforms)

1. **Docker Desktop** (macOS/Windows) or **Docker Engine** (Linux)
   - Minimum 8GB RAM allocated to Docker
   - At least 20GB free disk space
   - Docker Compose (included in Docker Desktop)

2. **Git** for cloning the repository

---

### macOS Setup

#### 1. Install Docker Desktop

1. Download Docker Desktop from [docker.com](https://www.docker.com/products/docker-desktop/)
2. Install and launch Docker Desktop
3. Configure Docker Desktop:
   - Open Docker Desktop
   - Go to **Settings** → **Resources**
   - Set **Memory** to at least 8GB (recommended: 12GB)
   - Set **CPUs** to at least 4 (recommended: 6-8)
   - Click **Apply & Restart**

#### 2. Verify Docker Installation

```bash
docker --version
docker compose version
```

#### 3. Clone the Repository

```bash
git clone https://github.com/sensein/BrainKB.git
cd BrainKB
```

#### 4. Continue to [Quick Start](#quick-start)

---

### Windows Setup

#### 1. Install WSL 2 (Windows Subsystem for Linux)

**Important**: Docker Desktop on Windows requires WSL 2.

1. Open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```

2. Restart your computer when prompted

3. After restart, complete the Ubuntu setup:
   - Set your username and password
   - Update Ubuntu: `sudo apt update && sudo apt upgrade`

#### 2. Install Docker Desktop

1. Download Docker Desktop from [docker.com](https://www.docker.com/products/docker-desktop/)
2. Install Docker Desktop
3. During installation, ensure **"Use WSL 2 instead of Hyper-V"** is selected
4. Launch Docker Desktop
5. Configure Docker Desktop:
   - Open Docker Desktop
   - Go to **Settings** → **Resources**
   - Set **Memory** to at least 8GB (recommended: 12GB)
   - Set **CPUs** to at least 4 (recommended: 6-8)
   - Go to **Settings** → **Resources** → **WSL Integration**
   - Enable integration with your WSL 2 Ubuntu distribution
   - Click **Apply & Restart**

#### 3. Verify Docker Installation

Open **Ubuntu** from the Start Menu (not PowerShell) and run:

```bash
docker --version
docker compose version
```

#### 4. Clone the Repository

**Inside Ubuntu terminal (WSL 2)**:

```bash
# Create a workspace directory
mkdir -p ~/workspace
cd ~/workspace

# Clone the repository
git clone https://github.com/sensein/BrainKB.git
cd BrainKB
```

**Important**: Always work inside WSL 2 (Ubuntu terminal), not in PowerShell or Windows Command Prompt, for better performance.

#### 5. Continue to [Quick Start](#quick-start)

---

### Linux Setup

#### 1. Install Docker

**Ubuntu/Debian:**
```bash
# Update package index
sudo apt-get update

# Install prerequisites
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Add Docker's official GPG key
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Set up the repository
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Add your user to docker group (to run without sudo)
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
```

**Fedora/RHEL/CentOS:**
```bash
sudo dnf install -y docker docker-compose-plugin
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
# Log out and back in
```

#### 2. Verify Docker Installation

```bash
docker --version
docker compose version
```

#### 3. Clone the Repository

```bash
git clone https://github.com/sensein/BrainKB.git
cd BrainKB
```

#### 4. Continue to [Quick Start](#quick-start)

---

## Quick Start

Once you have Docker installed and the repository cloned:

### 1. Configure Environment Variables

```bash
# Copy the environment template
cp env.template .env

# Edit .env with your configuration
# For local deployment, you can keep most defaults
# Make sure to change passwords for security
nano .env  # or use your preferred editor (vim, code, etc.)
```

**Important settings to change in `.env`:**
- `POSTGRES_PASSWORD` - Change from default
- `DJANGO_SUPERUSER_PASSWORD` - Change from default
- `OXIGRAPH_PASSWORD` - Change from default
- `PGADMIN_DEFAULT_PASSWORD` - Change from default

**Note**: The `OXIGRAPH_DATA_PATH` and `OXIGRAPH_TMP_PATH` variables are optional. Leave them commented out (or not set) to use Docker named volumes, which is recommended for local development.

### 2. Start All Services

```bash
# Make the start script executable
chmod +x start_services.sh

# Start all services
./start_services.sh
```

This script will:
- Auto-detect if GPU is available for Ollama
- Set up and start the Ollama service
- Pull the required Ollama model
- Start all BrainKB services

**First run will take several minutes** as Docker downloads images and builds containers.

### 3. Verify Services are Running

```bash
docker ps
```

You should see containers running:
- `brainkb-unified` - Main application services
- `brainkb-postgres` - PostgreSQL database
- `brainkb-oxigraph` - Knowledge graph database
- `brainkb-oxigraph-nginx` - Oxigraph reverse proxy
- `brainkb-pgadmin` - PostgreSQL admin interface
- `ollama` - Ollama AI model service

### 4. Access Services

Once all services are running, you can access:

| Service | URL | Default Credentials |
|---------|-----|---------------------|
| **API Token Manager** | http://localhost:8000 | admin / (your DJANGO_SUPERUSER_PASSWORD) |
| **Query Service API** | http://localhost:8010/docs | Requires JWT token |
| **ML Service API** | http://localhost:8007/docs | Requires JWT token |
| **Oxigraph SPARQL** | http://localhost:7878 | admin / (your OXIGRAPH_PASSWORD) |
| **pgAdmin** | http://localhost:5051 | (your PGADMIN_DEFAULT_EMAIL / PASSWORD) |

### 5. Create Your First User

1. Go to http://localhost:8000/admin
2. Log in with your Django superuser credentials
3. Create a new JWT user and assign appropriate scopes
4. Activate the user
5. Use the generated token to access Query and ML services

### 6. Stop Services

```bash
# Stop all services
./start_services.sh down

# Or stop specific service
./start_services.sh oxigraph down
```

---

## Configuration

### Data Persistence

BrainKB uses Docker named volumes for data persistence by default. This is recommended for local development:

- **postgres_data** - PostgreSQL database data
- **oxigraph_data** - Knowledge graph data
- **pgadmin_data** - pgAdmin configuration
- **ollama** - Ollama models and data
- **oxigraph_tmp** - Temporary files for Oxigraph

### Using Custom Data Paths (Advanced)

If you need to use a custom path for data storage (e.g., for production or shared storage), you can set environment variables in `.env`:

```bash
# Example: Use custom paths instead of named volumes
OXIGRAPH_DATA_PATH=/path/to/your/data
OXIGRAPH_TMP_PATH=/path/to/your/tmp
```

**Important Notes:**
- Paths must be absolute (not relative)
- **macOS**: Ensure the path is within your home directory or explicitly shared in Docker Desktop
  - Go to Docker Desktop → Settings → Resources → File Sharing
  - Add your custom path if it's outside the default shared locations
- **Windows**: Use WSL 2 paths (e.g., `/home/username/data`) or Windows paths (e.g., `C:\data`)
  - For Windows paths, use forward slashes: `/c/data` or `//c/data`
- **Linux**: Ensure the Docker user has read/write permissions to the path

### Resource Limits

You can adjust resource limits in `docker-compose.unified.yml`:

```yaml
deploy:
  resources:
    limits:
      cpus: '8.0'    # Maximum CPUs
      memory: 16G     # Maximum memory
    reservations:
      cpus: '2.0'    # Minimum CPUs reserved
      memory: 4G      # Minimum memory reserved
```

---

## Troubleshooting

### Common Issues

#### 1. "Mounts denied" or "Path not shared" Error

**macOS:**
1. Go to Docker Desktop → Settings → Resources → File Sharing
2. Ensure your project directory or custom paths are listed
3. If not, click the **+** button and add the directory
4. Click **Apply & Restart**

**Windows:**
1. Ensure you're running Docker Desktop with WSL 2 integration
2. Clone the repository inside WSL 2 (Ubuntu), not in Windows
3. Go to Docker Desktop → Settings → Resources → WSL Integration
4. Enable integration with your distribution

**Linux:**
Check directory permissions:
```bash
sudo chown -R $USER:$USER /path/to/BrainKB
```

#### 2. Port Already in Use

If you get "port already allocated" errors:

```bash
# Check what's using the port
# macOS/Linux:
sudo lsof -i :8000

# Windows (in PowerShell):
netstat -ano | findstr :8000

# Stop the conflicting service or change the port in .env
```

#### 3. Out of Memory Errors

Increase Docker memory allocation:
- Docker Desktop → Settings → Resources → Memory
- Set to at least 8GB (recommended: 12-16GB)

#### 4. Services Not Starting

Check logs:
```bash
# View all service logs
./start_services.sh logs -f

# View specific service logs
docker logs brainkb-unified
docker logs brainkb-postgres
docker logs brainkb-oxigraph
```

#### 5. Database Connection Errors

Wait for PostgreSQL to be fully ready:
```bash
# Check PostgreSQL health
docker ps

# The postgres container should show "healthy" status
# If not, wait a minute and check again
```

#### 6. Oxigraph Not Accessible

1. Check if Oxigraph is running:
   ```bash
   docker ps | grep oxigraph
   ```

2. Verify nginx authentication:
   - Username: `admin` (or your OXIGRAPH_USER from .env)
   - Password: Your OXIGRAPH_PASSWORD from .env

3. Check logs:
   ```bash
   docker logs brainkb-oxigraph
   docker logs brainkb-oxigraph-nginx
   ```

#### 7. Windows: Slow Performance

- Ensure you cloned the repository **inside WSL 2** (not in Windows file system)
- Access files through `/home/username/` paths, not `/mnt/c/`
- Windows file system access from WSL 2 is slow; keep everything in WSL 2

#### 8. Permission Denied on start_services.sh

```bash
chmod +x start_services.sh
```

---

## Advanced Usage

### Individual Service Control

```bash
# Start specific service
./start_services.sh postgres up

# Restart specific service
./start_services.sh brainkb-unified restart

# View specific service logs
./start_services.sh postgres logs -f

# Control microservices inside brainkb-unified
./start_services.sh query-service restart
./start_services.sh ml-service restart
./start_services.sh api-token-manager restart
```

### Rebuilding Containers

If you update the code or Dockerfile:

```bash
# Rebuild specific service
docker compose -f docker-compose.unified.yml build brainkb-unified

# Rebuild and restart
docker compose -f docker-compose.unified.yml up -d --build brainkb-unified
```

### Cleaning Up

```bash
# Stop and remove containers
./start_services.sh down

# Remove volumes (WARNING: This deletes all data!)
docker compose -f docker-compose.unified.yml down -v

# Remove unused images and free space
docker system prune -a
```

---

## Getting Help

- **Documentation**: https://sensein.group/brainkbdocs/
- **Issues**: https://github.com/sensein/BrainKB/issues
- **Contact**: For questions or support, please open an issue on GitHub or refer to the main repository README

---

## Next Steps

After successful deployment:

1. **Create Users**: Set up JWT users with appropriate scopes
2. **Load Data**: Use the Query Service to load your knowledge graphs
3. **Explore API**: Check out the API documentation at `/docs` endpoints
4. **Customize**: Adjust configuration in `.env` as needed

Happy Knowledge Graphing! 🧠📊
