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
    # Determine the path to the .env.development.development file based on the environment
    root_dir = os.path.dirname(os.path.abspath(__file__))
    env_file = os.path.join(root_dir, f".{env_name}")

    # Load environment variables from the .env file
    load_dotenv(dotenv_path=env_file)

    # Return a dictionary containing the loaded environment variables
    return {
        "ENV_STATE": os.getenv("ENV_STATE"),
        "DATABASE_URL": os.getenv("DATABASE_URL"),
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
        "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY"),

    #     Ingestion specific environment
        "RABBITMQ_USERNAME": os.getenv("RABBITMQ_USERNAME"),
        "RABBITMQ_PASSWORD": os.getenv("RABBITMQ_PASSWORD"),
        "RABBITMQ_URL": os.getenv("RABBITMQ_URL", "localhost"),
        "RABBITMQ_PORT": os.getenv("RABBITMQ_PORT", 5672),
        "RABBITMQ_VHOST": os.getenv("RABBITMQ_VHOST","/"),

        #query service
        "QUERY_URL": os.getenv("QUERY_URL", "localhost:8010"),


    }



