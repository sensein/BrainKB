
# BrainKB

BrainKB is a cutting-edge knowledge base platform designed to empower scientists worldwide by providing tools for searching, exploring, and visualizing Neuroscience knowledge through knowledge graphs (KGs). Additionally, BrainKB offers advanced tools that enable scientists to contribute new information to the platform, ensuring it remains the premier destination for neuroscience research.


BrainKB serves as a knowledge base platform that provides scientists worldwide with tools for searching, exploring, and visualizing Neuroscience knowledge represented by knowledge graphs (KGs). Moreover, BrainKB provides cutting-edge tools that enable scientists to contribute new information (or knowledge) to the platform, ensuring it remains the go-to destination for all neuroscience-related research needs.


## Organization 
- [Ingest Service](ingest_service) Provides the service related to data ingestion and consumption using RabbitMQ. Not used currently.
- [GraphDB](graphdb) The docker compose configuration of GraphDB.
- [JWT User & Scope Manager](APItokenmanager) A toolkit to manage JWT users and their permissions for API endpoint access.
- [Query Service](query_service) Provides the functionalities for querying (and updating) the knowledge graphs from the graph database.
- [RabbitMQ](rabbit-mq) The docker compose configuration of RabbitMQ.
- [SPARQL Queries](sparql_queries) List of SPARQL queries tested or used in BrainKB.

## Running

### Quick Start

#### 1. Setup Environment variables

**Important**: You MUST create a `.env` file and change default passwords for security.

```bash
# Copy the environment template
cp env.template .env

# Edit .env with your configuration
nano .env  # or use your preferred editor (vim, code, etc.)
```

**Required changes in `.env`:**
- `POSTGRES_PASSWORD` - Change from default
- `DB_PASSWORD` - Must match POSTGRES_PASSWORD
- `JWT_POSTGRES_DATABASE_PASSWORD` - Must match POSTGRES_PASSWORD
- `DJANGO_SUPERUSER_PASSWORD` - Set a secure password for Django admin
- `OXIGRAPH_PASSWORD` - Change from default
- `GRAPHDATABASE_PASSWORD` - Must match OXIGRAPH_PASSWORD
- `QUERY_SERVICE_JWT_SECRET_KEY` - Set a secure random string
- `ML_SERVICE_JWT_SECRET_KEY` - Set a secure random string

**Optional configuration:**
- `MONGO_DB_URL` - Required if using ML Service with MongoDB
- `OLLAMA_API_ENDPOINT` - Set to `http://host.docker.internal:11434` when using Docker
- Other service-specific settings as documented in `env.template`

**Validate your configuration:**
```bash
# Optional but recommended - validate your .env file
./validate_env.sh
```

#### 2. Start Services

**Recommended: Use the wrapper script (includes Ollama setup + pgAdmin config):**
```bash
chmod +x start_services.sh
./start_services.sh
```

#### 3. Access Services

Once started, services are accessible at:

- **API Token Manager (Django)**: `http://localhost:8000/`
  - Once you register JWT user you need to activate it using token manager. You can also assign permission.
- **Query Service (FastAPI)**: `http://localhost:8010/`
  - Now supports ingestion than just querying.
- **ML Service (FastAPI)**: `http://localhost:8007/`
  - Integrates StructSense
- **Oxigraph SPARQL**: `http://localhost:7878/` (password protected) graph database
- **pgAdmin**: `http://localhost:5051/`

### Troubleshooting

#### Services not accessible (localhost:8007, localhost:8010)

If you cannot access Query Service (port 8010) or ML Service (port 8007) after starting:

1. **Check if .env file exists and has valid configuration:**
   ```bash
   # Ensure .env file exists
   ls -la .env
   
   # Verify passwords are not default values
   grep "your_secure_password_change_this" .env
   # If this finds matches, update those passwords!
   ```

2. **Check service status inside the container:**
   ```bash
   # View all service statuses
   docker exec brainkb-unified supervisorctl status
   
   # If services show as EXITED or FATAL, check logs:
   docker exec brainkb-unified tail -n 50 /var/log/supervisor/query_service.err.log
   docker exec brainkb-unified tail -n 50 /var/log/supervisor/ml_service.err.log
   ```

3. **Restart individual services:**
   ```bash
   # Restart query service
   ./start_services.sh query-service restart
   
   # Restart ML service
   ./start_services.sh ml-service restart
   ```

4. **Check container health:**
   ```bash
   # View container health status
   docker ps --format "table {{.Names}}\t{{.Status}}"
   
   # View container logs
   docker logs brainkb-unified
   ```

5. **Common issues:**
   - **Database connection failures**: Ensure PostgreSQL passwords match across POSTGRES_PASSWORD, DB_PASSWORD, and JWT_POSTGRES_DATABASE_PASSWORD
   - **Missing environment variables**: Check logs for "environment variable not set" errors
   - **Port conflicts**: Ensure ports 8000, 8007, 8010 are not already in use by other applications

If you encounter Docker mount errors or issues with file sharing, please refer to the [Troubleshooting section in LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md#troubleshooting).



## Documentation
Please refer to the BrainKB documentation below for additional information regarding BrainKB, its rationale, deployment instructions, and lessons learned.
- [https://sensein.group/brainkbdocs/](https://sensein.group/brainkbdocs/)

## Contact
- Tek Raj Chhetri <tekraj@mit.edu>

## License

This project is licensed under the [Apache License 2.0](https://opensource.org/license/apache-2-0).

**Copyright © 2024–Present Senseable Intelligence Group**

You may obtain a copy of the license at: [Apache License, Version 2.0](https://opensource.org/license/apache-2-0)


