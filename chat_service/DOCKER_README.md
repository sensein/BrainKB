# Docker Setup with MySQL Caching

This document describes the Docker Compose setup for the chat service with MySQL-based caching.

## 🐳 **Docker Services Overview**

### **Development Environment** (`docker-compose-dev.yml`)
- **PostgreSQL Database**: PostgreSQL 15 for both user management and caching
- **Chat Service**: FastAPI application
- **pgAdmin**: Web interface for PostgreSQL management

### **Production Environment** (`docker-compose-prod.yml`)
- **PostgreSQL Database**: Optimized for production
- **Chat Service**: Production-ready FastAPI application

## 🚀 **Quick Start**

### **Development Setup**
```bash
# Start all services
docker-compose -f docker-compose-dev.yml up -d

# View logs
docker-compose -f docker-compose-dev.yml logs -f

# Stop services
docker-compose -f docker-compose-dev.yml down
```

### **Production Setup**
```bash
# Start production services
docker-compose -f docker-compose-prod.yml up -d

# View logs
docker-compose -f docker-compose-prod.yml logs -f

# Stop services
docker-compose -f docker-compose-prod.yml down
```

## 📊 **Service Ports**

| Service | Port | Description |
|---------|------|-------------|
| Chat Service | 8011 | Main API endpoint |
| PostgreSQL | 5432 | PostgreSQL database (user management + caching) |
| pgAdmin | 8081 | PostgreSQL web interface |

## 🔧 **Database Configuration**

### **PostgreSQL Database (User Management + Caching)**
- **Host**: `postgres` (container name)
- **Port**: 5432
- **Database**: `chat_db`
- **User**: `postgres`
- **Password**: `postgres_password` (dev) / `${JWT_POSTGRES_DATABASE_PASSWORD}` (prod)

## 🗄️ **Database Management**

### **Access PostgreSQL**
```bash
# Connect via command line
docker exec -it chat-postgres psql -U postgres -d chat_db

# Web interface: http://localhost:8081
# Email: admin@brainkb.org
# Password: admin_password
```

## 🔍 **Monitoring & Debugging**

### **View Service Logs**
```bash
# All services
docker-compose -f docker-compose-dev.yml logs

# Specific service
docker-compose -f docker-compose-dev.yml logs mysql-cache
docker-compose -f docker-compose-dev.yml logs app-dev-ml-service-agent
```

### **Check Service Health**
```bash
# Check all services
docker-compose -f docker-compose-dev.yml ps

# Check specific service
docker exec chat-cache-mysql mysqladmin ping -h localhost
docker exec chat-postgres pg_isready -U postgres
```

### **Database Operations**
```bash
# Backup PostgreSQL (includes both user data and cache)
docker exec chat-postgres pg_dump -U postgres chat_db > postgres_backup.sql

# Restore PostgreSQL
docker exec -i chat-postgres psql -U postgres chat_db < postgres_backup.sql
```

## 🛠️ **Environment Variables**

### **Development** (hardcoded in docker-compose-dev.yml)
```yaml
# PostgreSQL (User Management + Caching)
JWT_POSTGRES_DATABASE_HOST_URL: postgres
JWT_POSTGRES_DATABASE_PORT: 5432
JWT_POSTGRES_DATABASE_USER: postgres
JWT_POSTGRES_DATABASE_PASSWORD: postgres_password
JWT_POSTGRES_DATABASE_NAME: chat_db
```

### **Production** (from environment file)
```bash
# Set these in your .env file or environment
JWT_POSTGRES_DATABASE_HOST_URL=postgres
JWT_POSTGRES_DATABASE_PORT=5432
JWT_POSTGRES_DATABASE_USER=postgres
JWT_POSTGRES_DATABASE_PASSWORD=your_secure_password
JWT_POSTGRES_DATABASE_NAME=chat_db
```

## 📈 **Performance Optimization**

### **PostgreSQL Settings**
- **Connection Pool**: 10-100 connections
- **Memory**: 1-2GB allocated
- **TTL**: 1 hour default
- **Indexes**: Optimized for both user management and caching
- **JSONB Support**: Native JSON operations for cache metadata

## 🔒 **Security Considerations**

### **Development**
- Default passwords for easy setup
- Exposed ports for debugging
- Admin interfaces enabled

### **Production**
- Use strong passwords
- Limit port exposure
- Disable admin interfaces
- Use secrets management

## 🧹 **Maintenance**

### **Clean Up**
```bash
# Remove all containers and volumes
docker-compose -f docker-compose-dev.yml down -v

# Remove specific volumes
docker volume rm chat_service_postgres_data

# Clean up unused resources
docker system prune -a
```

### **Update Services**
```bash
# Pull latest images
docker-compose -f docker-compose-dev.yml pull

# Rebuild services
docker-compose -f docker-compose-dev.yml build --no-cache

# Restart services
docker-compose -f docker-compose-dev.yml up -d
```

## 🚨 **Troubleshooting**

### **Common Issues**

1. **PostgreSQL Connection Failed**:
   ```bash
   # Check PostgreSQL container
   docker logs chat-postgres
   
   # Check network connectivity
   docker exec app-dev-ml-service-agent ping postgres
   ```

3. **Cache Not Working**:
   ```bash
   # Check cache table
   docker exec -it chat-postgres psql -U postgres -d chat_db -c "\dt"
   
   # Check cache entries
   docker exec -it chat-postgres psql -U postgres -d chat_db -c "SELECT COUNT(*) FROM chat_cache;"
   ```

4. **Service Won't Start**:
   ```bash
   # Check resource usage
   docker stats
   
   # Check port conflicts
   netstat -tulpn | grep :8007
   ```

### **Log Analysis**
```bash
# Follow application logs
docker-compose -f docker-compose-dev.yml logs -f app-dev-ml-service-agent

# Check for errors
docker-compose -f docker-compose-dev.yml logs | grep -i error

# Check cache initialization
docker-compose -f docker-compose-dev.yml logs | grep -i "cache"
```

## 📚 **Additional Resources**

- [MySQL Documentation](https://dev.mysql.com/doc/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/) 