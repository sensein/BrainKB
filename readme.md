# BrainKB

BrainKB is a cutting-edge knowledge base platform designed to empower scientists worldwide by providing tools for searching, exploring, and visualizing Neuroscience knowledge through knowledge graphs (KGs). Additionally, BrainKB offers advanced tools that enable scientists to contribute new information to the platform, ensuring it remains the premier destination for neuroscience research.

## Organization

- **[WebApp](WebApp)**: Obsolete and will be removed after merging the pull request to the main branch.
- **[Ingest Service](ingest_service)**: Manages data ingestion and consumption using RabbitMQ.
- **[GraphDB](graphdb)**: Contains the Docker Compose configuration for GraphDB.
- **[JWT User & Scope Manager](APItokenmanager)**: A toolkit for managing JWT users and their permissions for API endpoint access.
- **[Query Service](query_service)**: Provides functionalities for querying and updating the knowledge graphs from the graph database.
- **[RabbitMQ](rabbit-mq)**: Contains the Docker Compose configuration for RabbitMQ.
- **[SPARQL Queries](sparql_queries)**: A collection of tested or utilized SPARQL queries in BrainKB.

## Documentation

For more information about BrainKB, including its rationale, deployment instructions, and lessons learned, please refer to the [BrainKB Documentation](https://sensein.group/brainkbdocs/).

## Contact

- **Tek Raj Chhetri**: [tekraj@mit.edu](mailto:tekraj@mit.edu)

## Acknowledgements

- **Aaron Kanzer**: [akanzer@mit.edu](mailto:akanzer@mit.edu) - Thank you for the code review.

## License

- © 2024-present
- Licensed under the [MIT License](https://opensource.org/license/mit).
