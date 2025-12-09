
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

For detailed platform-specific instructions (macOS, Windows, Linux), see **[LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md)**.

#### 1. Setup Environment variables

```bash
# Copy the environment template
cp env.template .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

**Important**: Change default passwords in `.env` for security.

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


