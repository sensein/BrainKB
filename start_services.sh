#!/bin/bash
# Wrapper script for docker-compose that auto-generates servers.json and sets up Ollama.
#
# Usage:
#   ./start_services.sh                          # Start all services: docker compose -f docker-compose.unified.yml up -d
#   ./start_services.sh down                     # Stop all services: docker compose -f docker-compose.unified.yml down
#   ./start_services.sh logs -f                  # View logs: docker compose -f docker-compose.unified.yml logs -f
#   ./start_services.sh <service> up             # Start a specific service (e.g., brainkb-unified, postgres)
#   ./start_services.sh <service> down            # Stop a specific service
#   ./start_services.sh <service> restart         # Restart a specific service
#   ./start_services.sh ollama up                 # Start Ollama (handled separately)
#   ./start_services.sh ollama down               # Stop Ollama
#
# Individual Microservices (inside brainkb-unified container):
#   ./start_services.sh query-service restart     # Restart only query service
#   ./start_services.sh ml-service restart        # Restart only ML service
#   ./start_services.sh api-token-manager restart  # Restart only API token manager
#   ./start_services.sh query-service status      # Check status of query service
#   ./start_services.sh query-service logs        # View logs of query service
#
# Available services:
#   - postgres, brainkb-unified, oxigraph, oxigraph-nginx, pgadmin, ollama
#   - query-service, ml-service, api-token-manager (microservices inside brainkb-unified)
#
# Features:
#   - Automatically detects GPU availability and uses GPU acceleration if available
#   - Sets up Ollama container (CPU or GPU mode) before starting services
#   - Loads the Ollama model specified in .env (OLLAMA_MODEL variable)
#   - Auto-generates pgAdmin servers.json via .docker-compose-hook.sh
#   - Supports individual service control
#
# Ollama Configuration:
#   - Model: Set OLLAMA_MODEL in .env (default: nomic-embed-text)
#   - Port: Set OLLAMA_PORT in .env (default: 11434)
#   - GPU: Automatically detected if nvidia-smi and nvidia-container-toolkit are available
#
# Optional: Make it your default docker-compose command by adding this alias
# to your ~/.bashrc or ~/.zshrc:
#   alias docker-compose='path/to/BrainKB/start_services.sh'


# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Check if .env file exists, if not provide helpful error message
if [ ! -f ".env" ]; then
    echo "ERROR: .env file not found!"
    echo ""
    echo "Please create a .env file from the template:"
    echo "  cp env.template .env"
    echo ""
    echo "Then edit .env with your configuration:"
    echo "  - Change all default passwords (POSTGRES_PASSWORD, DJANGO_SUPERUSER_PASSWORD, etc.)"
    echo "  - Configure Ollama settings if needed"
    echo "  - Review other settings as needed"
    echo ""
    echo "You can validate your configuration with:"
    echo "  ./validate_env.sh"
    echo ""
    echo "See env.template for all available options and documentation."
    exit 1
fi

# Validate .env file (only for 'up' commands, skip for other operations)
# This helps catch configuration issues early
if [[ "$1" == "up" ]] || [[ "$1" == "" ]]; then
    if [ -f "./validate_env.sh" ]; then
        # Run validation but don't exit on warnings (only on errors)
        if ! ./validate_env.sh; then
            echo ""
            echo "Please fix the configuration errors above before starting services."
            exit 1
        fi
    fi
fi

# Load environment variables from .env file FIRST
# This ensures the hook script has access to the correct environment variables
if [ -f ".env" ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Source the hook script if it exists (try both naming conventions)
# Hook script runs AFTER .env is loaded so it can use the correct values
if [ -f "docker-compose-hook.sh" ]; then
    source docker-compose-hook.sh
elif [ -f ".docker-compose-hook.sh" ]; then
    source .docker-compose-hook.sh
fi

# Function to handle Ollama operations
handle_ollama() {
    local command="$1"
    local ollama_container="ollama"
    local ollama_port="${OLLAMA_PORT:-11434}"
    local ollama_model="${OLLAMA_MODEL:-nomic-embed-text}"
    
    case "$command" in
        up|start)
            # Check if Ollama container already exists and is running
            if docker ps -a --format '{{.Names}}' | grep -q "^${ollama_container}$"; then
                if docker ps --format '{{.Names}}' | grep -q "^${ollama_container}$"; then
                    echo "Ollama container is already running"
                    # Check if model is loaded
                    if docker exec ${ollama_container} ollama list 2>/dev/null | grep -q "${ollama_model}"; then
                        echo "Ollama model '${ollama_model}' is already loaded"
                        return 0
                    fi
                else
                    echo "Starting existing Ollama container..."
                    docker start ${ollama_container} >/dev/null 2>&1
                fi
            else
                echo "Setting up Ollama..."
                
                # Check if GPU is available
                local use_gpu=false
                if command -v nvidia-smi >/dev/null 2>&1; then
                    if nvidia-smi >/dev/null 2>&1; then
                        # Check if nvidia-container-toolkit is available
                        if docker info 2>/dev/null | grep -q "nvidia"; then
                            use_gpu=true
                            echo "GPU detected - using GPU acceleration for Ollama"
                        else
                            echo "WARNING: GPU detected but nvidia-container-toolkit not configured. Using CPU mode."
                            echo "   Install nvidia-container-toolkit for GPU support: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html"
                        fi
                    fi
                fi
                
                # Start Ollama container
                if [ "$use_gpu" = true ]; then
                    echo "Starting Ollama with GPU support..."
                    docker run -d \
                        --gpus=all \
                        -v ollama:/root/.ollama \
                        -p ${ollama_port}:11434 \
                        --name ${ollama_container} \
                        --restart unless-stopped \
                        ollama/ollama >/dev/null 2>&1
                else
                    echo "Starting Ollama with CPU (no GPU detected)..."
                    docker run -d \
                        -v ollama:/root/.ollama \
                        -p ${ollama_port}:11434 \
                        --name ${ollama_container} \
                        --restart unless-stopped \
                        ollama/ollama >/dev/null 2>&1
                fi
                
                if [ $? -ne 0 ]; then
                    echo "ERROR: Failed to start Ollama container"
                    return 1
                fi
                
                echo "Waiting for Ollama to be ready..."
                local max_attempts=30
                local attempt=0
                while [ $attempt -lt $max_attempts ]; do
                    if docker exec ${ollama_container} ollama list >/dev/null 2>&1; then
                        echo "Ollama is ready"
                        break
                    fi
                    attempt=$((attempt + 1))
                    sleep 1
                done
                
                if [ $attempt -eq $max_attempts ]; then
                    echo "ERROR: Ollama failed to start within ${max_attempts} seconds"
                    return 1
                fi
            fi
            
            # Load the model if not already loaded
            if ! docker exec ${ollama_container} ollama list 2>/dev/null | grep -q "${ollama_model}"; then
                echo "Loading Ollama model '${ollama_model}' (this may take a while on first run)..."
                docker exec ${ollama_container} ollama pull ${ollama_model} >/dev/null 2>&1
                if [ $? -eq 0 ]; then
                    echo "Ollama model '${ollama_model}' loaded successfully"
                else
                    echo "Failed to load model '${ollama_model}'. You can load it manually later with:"
                    echo "   docker exec ${ollama_container} ollama pull ${ollama_model}"
                fi
            fi
            ;;
        down|stop)
            if docker ps --format '{{.Names}}' | grep -q "^${ollama_container}$"; then
                echo "Stopping Ollama container..."
                docker stop ${ollama_container} >/dev/null 2>&1
                echo "Ollama stopped"
            else
                echo "Ollama container is not running"
            fi
            ;;
        restart)
            handle_ollama down
            sleep 2
            handle_ollama up
            ;;
        *)
            echo "Unknown Ollama command: $command"
            echo "Available commands: up, down, restart, stop, start"
            return 1
            ;;
    esac
}
if ! docker network inspect brainkb-network >/dev/null 2>&1; then
    echo "Creating docker network external - brainkb-network"
    docker network create brainkb-network
fi

# Function to setup and start Ollama (for automatic setup on 'up' commands)
setup_ollama() {
    handle_ollama up
}

# Function to check if services are accessible after startup
check_services_health() {
    local unified_container="brainkb-unified"
    
    # API endpoint constants
    local API_TOKEN_ENDPOINT="http://localhost:8000/"
    local QUERY_SERVICE_ENDPOINT="http://localhost:8010/api/"
    local ML_SERVICE_ENDPOINT="http://localhost:8007/api/"
    
    # Wait a bit for services to start
    echo ""
    echo "Waiting for services to start..."
    sleep 5
    
    # Check if container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${unified_container}$"; then
        echo "WARNING: Container '${unified_container}' is not running"
        return 1
    fi
    
    echo "Checking service health..."
    
    # Check supervisor status
    local supervisor_status=$(docker exec ${unified_container} supervisorctl status 2>&1)
    
    if [ $? -ne 0 ]; then
        echo "WARNING: Cannot connect to supervisor in '${unified_container}'"
        echo "The container may still be starting up. Please wait a moment and check:"
        echo "  docker logs ${unified_container}"
        return 1
    fi
    
    # Parse supervisor status and show service states
    echo ""
    echo "Service Status:"
    echo "---------------"
    echo "$supervisor_status" | while IFS= read -r line; do
        service_name=$(echo "$line" | awk '{print $1}')
        service_state=$(echo "$line" | awk '{print $2}')
        
        if [ "$service_state" = "RUNNING" ]; then
            echo "  ✓ $service_name: $service_state"
        else
            echo "  ✗ $service_name: $service_state"
            if [ "$service_name" = "query_service" ] || [ "$service_name" = "ml_service" ] || [ "$service_name" = "api_tokenmanager" ]; then
                echo "    To view logs: docker exec ${unified_container} tail -n 50 /var/log/supervisor/${service_name}.err.log"
            fi
        fi
    done
    
    # Check if services are accessible via HTTP
    echo ""
    echo "Checking HTTP endpoints..."
    echo "--------------------------"
    
    # API Token Manager (port 8000)
    if curl -s -f "$API_TOKEN_ENDPOINT" > /dev/null 2>&1; then
        echo "  ✓ API Token Manager: $API_TOKEN_ENDPOINT (accessible)"
    else
        echo "  ✗ API Token Manager: $API_TOKEN_ENDPOINT (not responding yet)"
        echo "    This service may still be starting. Check logs:"
        echo "    docker exec ${unified_container} tail -n 50 /var/log/supervisor/api_tokenmanager.err.log"
    fi
    
    # Query Service (port 8010)
    if curl -s -f "$QUERY_SERVICE_ENDPOINT" > /dev/null 2>&1; then
        echo "  ✓ Query Service: http://localhost:8010/ (accessible)"
    else
        echo "  ✗ Query Service: http://localhost:8010/ (not responding yet)"
        echo "    This service may still be starting. Check logs:"
        echo "    docker exec ${unified_container} tail -n 50 /var/log/supervisor/query_service.err.log"
    fi
    
    # ML Service (port 8007)
    if curl -s -f "$ML_SERVICE_ENDPOINT" > /dev/null 2>&1; then
        echo "  ✓ ML Service: http://localhost:8007/ (accessible)"
    else
        echo "  ✗ ML Service: http://localhost:8007/ (not responding yet)"
        echo "    This service may still be starting. Check logs:"
        echo "    docker exec ${unified_container} tail -n 50 /var/log/supervisor/ml_service.err.log"
    fi
    
    echo ""
    echo "Note: Services may take 30-90 seconds to fully start."
    echo "If services are not accessible after 2 minutes, check the logs using the commands above."
    echo ""
}

# If no arguments provided, default to "up -d"
if [ $# -eq 0 ]; then
    set -- up -d
fi

# Check if first argument is a service name (not a docker-compose command)
# Docker-compose commands: up, down, start, stop, restart, ps, logs, etc.
# Service names: postgres, brainkb-unified, oxigraph, oxigraph-nginx, pgadmin, ollama
DOCKER_COMPOSE_COMMANDS="up down start stop restart ps logs exec pull push build config create events kill pause port ps top unpause version"
SERVICE_NAME=""
COMMAND_ARGS=()

# Function to get supervisor program name from user-friendly service name
# Supports both hyphenated and underscore versions
get_supervisor_name() {
    local service_name="$1"
    # Normalize service name (convert underscores to hyphens)
    local normalized=$(echo "$service_name" | tr '_' '-')
    
    case "$normalized" in
        query-service)
            echo "query_service"
            ;;
        ml-service)
            echo "ml_service"
            ;;
        api-token-manager|api-tokenmanager|token-manager)
            echo "api_tokenmanager"
            ;;
        *)
            echo ""
            ;;
    esac
}

# Function to handle individual microservices inside brainkb-unified container
handle_microservice() {
    local service_name="$1"
    local command="$2"
    local unified_container="brainkb-unified"
    local supervisor_name=$(get_supervisor_name "$service_name")
    
    if [ -z "$supervisor_name" ]; then
        echo "ERROR: Unknown microservice: $service_name"
        echo "Available microservices:"
        echo "  - query-service (or query_service)"
        echo "  - ml-service (or ml_service)"
        echo "  - api-token-manager (or api_tokenmanager, token-manager)"
        return 1
    fi
    
    # Check if unified container is running
    if ! docker ps --format '{{.Names}}' | grep -q "^${unified_container}$"; then
        echo "ERROR: Container '${unified_container}' is not running"
        echo "   Start it first with: ./start_services.sh brainkb-unified up"
        return 1
    fi
    
    # Check if supervisor is running inside the container
    # Try to get supervisor status - if it fails, supervisor isn't ready
    # Wait a bit and retry if container just started
    local max_retries=3
    local retry=0
    local supervisor_ready=false
    
    while [ $retry -lt $max_retries ]; do
        if docker exec ${unified_container} supervisorctl status >/dev/null 2>&1; then
            supervisor_ready=true
            break
        fi
        retry=$((retry + 1))
        if [ $retry -lt $max_retries ]; then
            sleep 2
        fi
    done
    
    if [ "$supervisor_ready" = false ]; then
        # Check if supervisor is actually running by checking the PID
        local supervisor_pid=$(docker exec ${unified_container} cat /var/run/supervisord.pid 2>/dev/null)
        if [ -n "$supervisor_pid" ]; then
            echo "ERROR: Supervisor is running (PID: $supervisor_pid), but socket is not accessible."
            echo "   The supervisor socket at /var/run/supervisor.sock is missing."
            echo "   This typically happens when the container was built before the socket configuration was added."
            echo ""
            echo "   Attempting to rebuild the container with updated supervisor configuration..."
            echo ""
            
            # Stop the container
            echo "Stopping ${unified_container}..."
            if docker compose version >/dev/null 2>&1; then
                docker compose -f docker-compose.unified.yml stop ${unified_container} >/dev/null 2>&1
            else
                docker-compose -f docker-compose.unified.yml stop ${unified_container} >/dev/null 2>&1
            fi
            
            # Rebuild the container
            echo "Rebuilding ${unified_container} with updated supervisor configuration..."
            if docker compose version >/dev/null 2>&1; then
                docker compose -f docker-compose.unified.yml build --no-cache ${unified_container}
                rebuild_status=$?
            elif command -v docker-compose >/dev/null 2>&1; then
                docker-compose -f docker-compose.unified.yml build --no-cache ${unified_container}
                rebuild_status=$?
            else
                echo "ERROR: Neither 'docker compose' nor 'docker-compose' found"
                return 1
            fi
            
            if [ $rebuild_status -eq 0 ]; then
                echo ""
                echo "Rebuild successful. Starting container..."
                if docker compose version >/dev/null 2>&1; then
                    docker compose -f docker-compose.unified.yml up -d ${unified_container}
                else
                    docker-compose -f docker-compose.unified.yml up -d ${unified_container}
                fi
                
                echo "Waiting for container to be ready..."
                sleep 10
                
                # Retry supervisor check
                local retry_count=0
                while [ $retry_count -lt 5 ]; do
                    if docker exec ${unified_container} supervisorctl status >/dev/null 2>&1; then
                        echo "Supervisor socket is now accessible. Retrying your command..."
                        # Retry the original command
                        docker exec ${unified_container} supervisorctl ${command} ${supervisor_name}
                        return $?
                    fi
                    retry_count=$((retry_count + 1))
                    sleep 2
                done
                
                echo "WARNING: Supervisor socket still not accessible after rebuild."
                echo "   Try restarting: ./start_services.sh brainkb-unified restart"
                return 1
            else
                echo "ERROR: Rebuild failed. Please rebuild manually:"
                echo "   docker-compose -f docker-compose.unified.yml build --no-cache brainkb-unified"
                return 1
            fi
        else
            echo "ERROR: Supervisor does not appear to be running inside '${unified_container}'."
            echo "   The container may still be starting up. Wait a moment and try again."
            echo "   Or restart: ./start_services.sh brainkb-unified restart"
        fi
        return 1
    fi
    
    case "$command" in
        restart)
            echo "Restarting ${service_name} (${supervisor_name})..."
            docker exec ${unified_container} supervisorctl restart ${supervisor_name}
            if [ $? -eq 0 ]; then
                echo "${service_name} restarted successfully"
            else
                echo "ERROR: Failed to restart ${service_name}"
                return 1
            fi
            ;;
        stop)
            echo "Stopping ${service_name} (${supervisor_name})..."
            docker exec ${unified_container} supervisorctl stop ${supervisor_name}
            if [ $? -eq 0 ]; then
                echo "${service_name} stopped successfully"
            else
                echo "ERROR: Failed to stop ${service_name}"
                return 1
            fi
            ;;
        start|up)
            echo "Starting ${service_name} (${supervisor_name})..."
            docker exec ${unified_container} supervisorctl start ${supervisor_name}
            if [ $? -eq 0 ]; then
                echo "${service_name} started successfully"
            else
                echo "ERROR: Failed to start ${service_name}"
                return 1
            fi
            ;;
        status)
            echo "Status of ${service_name} (${supervisor_name}):"
            docker exec ${unified_container} supervisorctl status ${supervisor_name}
            ;;
        logs)
            echo "Logs for ${service_name} (${supervisor_name}):"
            echo "   (Press Ctrl+C to exit)"
            docker exec ${unified_container} tail -f /var/log/supervisor/${supervisor_name}.out.log
            ;;
        *)
            echo "ERROR: Unknown command: $command"
            echo "Available commands: start, stop, restart, status, logs"
            return 1
            ;;
    esac
}

# Check if first argument is "ollama" (handled separately)
if [ "$1" = "ollama" ]; then
    if [ $# -lt 2 ]; then
        echo "Usage: $0 ollama <command>"
        echo "Commands: up, down, restart, stop, start"
        exit 1
    fi
    handle_ollama "$2"
    exit $?
fi

# Check if first argument is a microservice name
SUPERVISOR_NAME=$(get_supervisor_name "$1")
if [ -n "$SUPERVISOR_NAME" ]; then
    if [ $# -lt 2 ]; then
        echo "Usage: $0 $1 <command>"
        echo "Commands: start, stop, restart, status, logs"
        exit 1
    fi
    handle_microservice "$1" "$2"
    exit $?
fi

# Check if first argument looks like a service name (not a docker-compose command)
if [[ ! " $DOCKER_COMPOSE_COMMANDS " =~ " $1 " ]] && [[ "$1" != "-"* ]]; then
    # First argument is likely a service name
    SERVICE_NAME="$1"
    shift
    COMMAND_ARGS=("$@")
    
    # If no command provided after service name, default to "up"
    if [ ${#COMMAND_ARGS[@]} -eq 0 ]; then
        COMMAND_ARGS=("up" "-d")
    fi
else
    # First argument is a docker-compose command
    COMMAND_ARGS=("$@")
    
    # Setup Ollama before starting services (only for up/start commands)
    if [[ "$1" == "up" ]] || [[ "$1" == "start" ]]; then
        setup_ollama
    fi
fi

# Check if -f flag is provided, if not, default to docker-compose.unified.yml
HAS_FILE_FLAG=false
for arg in "${COMMAND_ARGS[@]}"; do
    if [ "$arg" = "-f" ] || [ "$arg" = "--file" ]; then
        HAS_FILE_FLAG=true
        break
    fi
done

# Build the final command
FINAL_ARGS=()
if [ "$HAS_FILE_FLAG" = false ]; then
    FINAL_ARGS+=("-f" "docker-compose.unified.yml")
fi

# Add service name if specified
if [ -n "$SERVICE_NAME" ]; then
    FINAL_ARGS+=("${COMMAND_ARGS[@]}" "$SERVICE_NAME")
else
    FINAL_ARGS+=("${COMMAND_ARGS[@]}")
fi

# Detect which docker-compose command is available
# Try docker compose (plugin, newer) first, then docker-compose (standalone, older)
DOCKER_COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DOCKER_COMPOSE_CMD="docker-compose"
else
    echo " Error: Neither 'docker compose' nor 'docker-compose' found in PATH"
    echo " Please install Docker Compose: https://docs.docker.com/compose/install/"
    exit 1
fi

# Execute docker-compose command with proper quoting
# Note: DOCKER_COMPOSE_CMD is safe here as it's set by us, not user input
eval "$DOCKER_COMPOSE_CMD \"\${FINAL_ARGS[@]}\""
COMPOSE_EXIT_CODE=$?

# If this was an 'up' command and it succeeded, check service health
if [ $COMPOSE_EXIT_CODE -eq 0 ]; then
    # Check if this was an 'up' command (not for individual services)
    if [[ " ${FINAL_ARGS[@]} " =~ " up " ]] && [ -z "$SERVICE_NAME" ]; then
        check_services_health
    fi
fi

exit $COMPOSE_EXIT_CODE

