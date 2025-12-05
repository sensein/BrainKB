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


def load_environment(env_name="production"):
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
    # query_service/core/ -> query_service/ -> BrainKB/
    project_root = os.path.dirname(os.path.dirname(root_dir))
    
    # Always load from root .env file (used by docker-compose)
    root_env_file = os.path.join(project_root, ".env")
    if os.path.exists(root_env_file):
        load_dotenv(dotenv_path=root_env_file, override=False)

    # Return a dictionary containing the loaded environment variables
    return {
        "ENV_STATE": os.getenv("ENV_STATE", "dev"),
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
        "JWT_SECRET_KEY": os.getenv("QUERY_SERVICE_JWT_SECRET_KEY"),
        # service specific
        "GRAPHDATABASE_USERNAME": os.getenv("GRAPHDATABASE_USERNAME"),
        "GRAPHDATABASE_PASSWORD": os.getenv("GRAPHDATABASE_PASSWORD"),
        "GRAPHDATABASE_HOSTNAME": os.getenv(
            "GRAPHDATABASE_HOSTNAME", "https://db.brainkb.org"
        ),
        "GRAPHDATABASE_PORT": os.getenv("GRAPHDATABASE_PORT", 7878),
        "GRAPHDATABASE_TYPE": os.getenv("GRAPHDATABASE_TYPE", "OXIGRAPH"),
        "GRAPHDATABASE_REPOSITORY": os.getenv("GRAPHDATABASE_REPOSITORY"),
        # Data release
        "RAPID_RELEASE_FILE": os.getenv("RAPID_RELEASE_FILE"),
        # Default named graph for ingestion
        "DEFAULT_NAMED_GRAPH": os.getenv("DEFAULT_NAMED_GRAPH", "https:test.brainkb.org/"),
    }
