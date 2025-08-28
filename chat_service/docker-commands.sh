#!/bin/bash

# Docker Compose Commands for Chat Service with MySQL Caching
# Usage: ./docker-commands.sh [command]

case "$1" in
    "dev")
        echo "Starting development environment with admin tools..."
        docker compose -f docker-compose-dev.yml -f docker-compose.override.yml up -d
        ;;
    "dev-only")
        echo "Starting development environment without admin tools..."
        docker compose -f docker-compose-dev.yml up -d
        ;;
    "prod")
        echo "Starting production environment..."
        docker compose -f docker-compose-prod.yml up -d
        ;;
    "admin-only")
        echo "Starting admin tools only (requires external PostgreSQL)..."
        docker compose -f docker-compose-admin.yml up -d
        ;;
    "logs")
        echo "Showing logs for development environment..."
        docker compose -f docker-compose-dev.yml -f docker-compose.override.yml logs -f
        ;;
    "logs-prod")
        echo "Showing logs for production environment..."
        docker compose -f docker-compose-prod.yml logs -f
        ;;
    "stop")
        echo "Stopping development environment..."
        docker compose -f docker-compose-dev.yml -f docker-compose.override.yml down
        ;;
    "stop-prod")
        echo "Stopping production environment..."
        docker compose -f docker-compose-prod.yml down
        ;;
    "clean")
        echo "Stopping and removing all containers and volumes..."
        docker compose -f docker-compose-dev.yml -f docker-compose.override.yml down -v
        docker compose -f docker-compose-prod.yml down -v
        ;;
    "status")
        echo "Checking service status..."
        docker compose -f docker-compose-dev.yml -f docker-compose.override.yml ps
        ;;
    "postgres")
        echo "Connecting to PostgreSQL database..."
        docker exec -it chat-postgres psql -U postgres -d chat_db
        ;;
    "cache-stats")
        echo "Getting cache statistics..."
        curl -X GET "http://localhost:8007/api/chat/cache/stats"
        ;;
    "health")
        echo "Checking service health..."
        curl -f http://localhost:8007/api/health || echo "Service not responding"
        ;;
    *)
        echo "Usage: $0 {dev|dev-only|prod|admin-only|logs|logs-prod|stop|stop-prod|clean|status|postgres|cache-stats|health}"
        echo ""
        echo "Commands:"
        echo "  dev          - Start development environment with admin tools"
        echo "  dev-only     - Start development environment without admin tools"
        echo "  prod         - Start production environment"
        echo "  admin-only   - Start admin tools only (requires external PostgreSQL)"
        echo "  logs         - Show development logs"
        echo "  logs-prod    - Show production logs"
        echo "  stop         - Stop development environment"
        echo "  stop-prod    - Stop production environment"
        echo "  clean        - Stop and remove all containers and volumes"
        echo "  status       - Check service status"
        echo "  postgres     - Connect to PostgreSQL database"
        echo "  cache-stats  - Get cache statistics"
        echo "  health       - Check service health"
        exit 1
        ;;
esac 