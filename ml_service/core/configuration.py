# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : configuration.py
# @Software: PyCharm

import os

from dotenv import load_dotenv


def load_environment(env_name="env"):
    """
    Load environment variables from the specified .env.development.development file.

    Args:
        env_name (str): Name of the environment (e.g., "production", "development").
                        Defaults to "development".

    Returns:
        dict: A dictionary containing the loaded environment variables.
    """
    # Determine the path to the .env file based on the environment
    # Always fall back to root .env file - service-specific .env files are removed
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Traverse up to project root (BrainKB/)
    # ml_service/core/ -> ml_service/ -> BrainKB/
    project_root = os.path.dirname(os.path.dirname(root_dir))
    
    # Always load from root .env file (used by docker-compose)
    root_env_file = os.path.join(project_root, ".env")
    if os.path.exists(root_env_file):
        load_dotenv(dotenv_path=root_env_file, override=False)

    # Return a dictionary containing the loaded environment variables
    return {
        "ENV_STATE": os.getenv("ENV_STATE"),
        "LOGTAIL_API_KEY": os.getenv("LOGTAIL_API_KEY"),
        "JWT_POSTGRES_DATABASE_HOST_URL": os.getenv("JWT_POSTGRES_DATABASE_HOST_URL"),
        "JWT_POSTGRES_DATABASE_PORT": os.getenv("JWT_POSTGRES_DATABASE_PORT"),
        "JWT_POSTGRES_DATABASE_USER": os.getenv("JWT_POSTGRES_DATABASE_USER"),
        "JWT_POSTGRES_TABLE_USER": os.getenv("JWT_POSTGRES_TABLE_USER", "Web_jwtuser"),
        "JWT_POSTGRES_TABLE_SCOPE": os.getenv("JWT_POSTGRES_TABLE_SCOPE", "Web_scope"),
        "JWT_POSTGRES_TABLE_USER_SCOPE_REL": os.getenv(
            "JWT_POSTGRES_TABLE_USER_SCOPE_REL", "Web_jwtuser_scopes"
        ),
        "JWT_POSTGRES_DATABASE_PASSWORD": os.getenv("JWT_POSTGRES_DATABASE_PASSWORD"),
        "JWT_POSTGRES_DATABASE_NAME": os.getenv("JWT_POSTGRES_DATABASE_NAME"),
        "JWT_ALGORITHM": os.getenv("JWT_ALGORITHM", "HS256"),
        "JWT_SECRET_KEY": os.getenv("ML_SERVICE_JWT_SECRET_KEY"),

    #     Ingestion specific environment
        "RABBITMQ_USERNAME": os.getenv("RABBITMQ_USERNAME"),
        "RABBITMQ_PASSWORD": os.getenv("RABBITMQ_PASSWORD"),
        "RABBITMQ_URL": os.getenv("RABBITMQ_URL", "localhost"),
        "RABBITMQ_PORT": os.getenv("RABBITMQ_PORT", 5672),
        "RABBITMQ_VHOST": os.getenv("RABBITMQ_VHOST","/"),

        #query service
        "QUERY_SERVICE_BASE_URL": os.getenv("QUERY_SERVICE_BASE_URL", "localhost:8010"),

        #mongodb
        "MONGO_DB_URL": os.getenv("MONGO_DB_URL"),
        "NER_DATABASE": os.getenv("NER_DATABASE","ner_database"),
        "NER_COLLECTION": os.getenv("NER_COLLECTION","ner_collection"),

        #structsense
        "ENABLE_KG_SOURCE": os.getenv("ENABLE_KG_SOURCE", "False"),
        "ONTOLOGY_DATABASE": os.getenv("ONTOLOGY_DATABASE", "ontology_database_agent_test1"),
        "WEAVIATE_GRPC_HOST": os.getenv("WEAVIATE_GRPC_HOST"),
        "WEAVIATE_HTTP_HOST": os.getenv("WEAVIATE_HTTP_HOST"),
        "WEAVIATE_API_KEY": os.getenv("WEAVIATE_API_KEY"),

        "EXTERNAL_PDF_EXTRACTION_SERVICE": os.getenv("EXTERNAL_PDF_EXTRACTION_SERVICE", "True"),
        "GROBID_SERVER_URL_OR_EXTERNAL_SERVICE": os.getenv("GROBID_SERVER_URL_OR_EXTERNAL_SERVICE", "http://localhost:8070"),
        "OLLAMA_API_ENDPOINT": os.getenv("OLLAMA_API_ENDPOINT", "http://localhost:11434"), #for docker "http://host.docker.internal:11434"
        "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL", "nomic-embed-text"),

    }



