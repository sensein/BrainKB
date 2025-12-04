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

"""
Configuration settings for the BrainKB Chat Service.
"""

import os
from typing import Optional
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
    # chat_service/core/ -> chat_service/ -> BrainKB/
    project_root = os.path.dirname(os.path.dirname(root_dir))
    
    # Always load from root .env file (used by docker-compose)
    root_env_file = os.path.join(project_root, ".env")
    if os.path.exists(root_env_file):
        load_dotenv(dotenv_path=root_env_file, override=False)

    # Return a dictionary containing the loaded environment variables
    return {
        "ENV_STATE": os.getenv("ENV_STATE"),
        "LOGTAIL_API_KEY": os.getenv("LOGTAIL_API_KEY"),
        
        # PostgreSQL Database Configuration
        "JWT_POSTGRES_DATABASE_HOST_URL": os.getenv("JWT_POSTGRES_DATABASE_HOST_URL"),
        "JWT_POSTGRES_DATABASE_PORT": os.getenv("JWT_POSTGRES_DATABASE_PORT"),
        "JWT_POSTGRES_DATABASE_USER": os.getenv("JWT_POSTGRES_DATABASE_USER"),
        "JWT_POSTGRES_DATABASE_PASSWORD": os.getenv("JWT_POSTGRES_DATABASE_PASSWORD"),
        "JWT_POSTGRES_DATABASE_NAME": os.getenv("JWT_POSTGRES_DATABASE_NAME"),
        
        # PostgreSQL Table Configuration
        "JWT_POSTGRES_TABLE_USER": os.getenv("JWT_POSTGRES_TABLE_USER", "Web_jwtuser"),
        "JWT_POSTGRES_TABLE_SCOPE": os.getenv("JWT_POSTGRES_TABLE_SCOPE", "Web_scope"),
        "JWT_POSTGRES_TABLE_USER_SCOPE_REL": os.getenv(
            "JWT_POSTGRES_TABLE_USER_SCOPE_REL", "Web_jwtuser_scopes"
        ),
        
        # JWT Configuration
        "JWT_ALGORITHM": os.getenv("JWT_ALGORITHM", "HS256"),
        "JWT_SECRET_KEY": os.getenv("CHAT_SERVICE_JWT_SECRET_KEY"),

        "JWT_BEARER_TOKEN_URL": os.getenv("JWT_BEARER_TOKEN_URL"),
        "JWT_LOGIN_EMAIL": os.getenv("JWT_LOGIN_EMAIL"),
        "JWT_LOGIN_PASSWORD": os.getenv("JWT_LOGIN_PASSWORD"),





        # Query Service Configuration
        "QUERY_URL": os.getenv("QUERY_URL", "localhost:8010"),
        
        # OpenRouter API Configuration
        "OPENROUTER_API_KEY": os.getenv("OPENROUTER_API_KEY"),
        "OPENROUTER_MODEL": os.getenv("OPENROUTER_MODEL", "openai/gpt-4"),
        "OPENROUTER_API_URL": os.getenv("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions"),
        
        # Chat Service Configuration
        "CHAT_SERVICE_NAME": os.getenv("CHAT_SERVICE_NAME", "BrainKB Chat Service"),
        "CHAT_SERVICE_URL": os.getenv("CHAT_SERVICE_URL", "https://brainkb.org"),
        
        # Cache Configuration
        "CACHE_TTL_SECONDS": os.getenv("CACHE_TTL_SECONDS", 3600),
        "CACHE_MAX_SIZE": os.getenv("CACHE_MAX_SIZE", 1000),
        
        # Logging Configuration
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "LOG_FORMAT": os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
    }


class Configuration:
    """
    Centralized configuration class for the BrainKB Chat Service.
    Provides easy access to all environment variables with proper defaults.
    """
    
    def __init__(self, env_name: str = "env"):
        """
        Initialize configuration with environment variables.
        
        Args:
            env_name (str): Name of the environment file (e.g., "env", "production")
        """
        self._env_vars = load_environment(env_name)
    
    # Environment State
    @property
    def env_state(self) -> Optional[str]:
        return self._env_vars.get("ENV_STATE")
    
    # PostgreSQL Database Configuration
    @property
    def postgres_host(self) -> Optional[str]:
        return self._env_vars.get("JWT_POSTGRES_DATABASE_HOST_URL")
    
    @property
    def postgres_port(self) -> Optional[str]:
        return self._env_vars.get("JWT_POSTGRES_DATABASE_PORT")
    
    @property
    def postgres_user(self) -> Optional[str]:
        return self._env_vars.get("JWT_POSTGRES_DATABASE_USER")
    
    @property
    def postgres_password(self) -> Optional[str]:
        return self._env_vars.get("JWT_POSTGRES_DATABASE_PASSWORD")
    
    @property
    def postgres_database(self) -> Optional[str]:
        return self._env_vars.get("JWT_POSTGRES_DATABASE_NAME")
    
    # PostgreSQL Table Configuration
    @property
    def postgres_table_user(self) -> str:
        return self._env_vars.get("JWT_POSTGRES_TABLE_USER", "Web_jwtuser")
    
    @property
    def postgres_table_scope(self) -> str:
        return self._env_vars.get("JWT_POSTGRES_TABLE_SCOPE", "Web_scope")
    
    @property
    def postgres_table_user_scope_rel(self) -> str:
        return self._env_vars.get("JWT_POSTGRES_TABLE_USER_SCOPE_REL", "Web_jwtuser_scopes")
    
    # JWT Configuration
    @property
    def jwt_algorithm(self) -> str:
        return self._env_vars.get("JWT_ALGORITHM", "HS256")
    
    @property
    def jwt_secret_key(self) -> Optional[str]:
        return self._env_vars.get("JWT_SECRET_KEY")

    @property
    def jwt_bearer_token_url(self) -> str:
        return self._env_vars.get("JWT_BEARER_TOKEN_URL")

    @property
    def jwt_login_username(self) -> str:
        return self._env_vars.get("JWT_LOGIN_EMAIL")

    @property
    def jwt_login_password(self) -> str:
        return self._env_vars.get("JWT_LOGIN_PASSWORD")
    
    # Query Service Configuration
    @property
    def query_url(self) -> str:
        return self._env_vars.get("QUERY_URL", "localhost:8010")
    
    # OpenRouter API Configuration
    @property
    def openrouter_api_key(self) -> Optional[str]:
        return self._env_vars.get("OPENROUTER_API_KEY")
    
    @property
    def openrouter_model(self) -> str:
        return self._env_vars.get("OPENROUTER_MODEL", "openai/gpt-4")
    
    @property
    def openrouter_api_url(self) -> str:
        return self._env_vars.get("OPENROUTER_API_URL", "https://openrouter.ai/api/v1/chat/completions")
    
    # Chat Service Configuration
    @property
    def chat_service_name(self) -> str:
        return self._env_vars.get("CHAT_SERVICE_NAME", "BrainKB Chat Service")
    
    @property
    def chat_service_url(self) -> str:
        return self._env_vars.get("CHAT_SERVICE_URL", "https://brainkb.org")
    
    # Cache Configuration
    @property
    def cache_ttl_seconds(self) -> int:
        return int(self._env_vars.get("CACHE_TTL_SECONDS", 3600))
    
    @property
    def cache_max_size(self) -> int:
        return int(self._env_vars.get("CACHE_MAX_SIZE", 1000))
    
    # Logging Configuration
    @property
    def log_level(self) -> str:
        return self._env_vars.get("LOG_LEVEL", "INFO")
    
    @property
    def log_format(self) -> str:
        return self._env_vars.get("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    # Logtail Configuration
    @property
    def logtail_api_key(self) -> Optional[str]:
        return self._env_vars.get("LOGTAIL_API_KEY")
    
    def get_postgres_settings(self) -> dict:
        """Get PostgreSQL database settings as a dictionary"""
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "user": self.postgres_user,
            "password": self.postgres_password,
            "database": self.postgres_database,
            "min_size": 10,
            "max_size": 100,
            "command_timeout": 60,
            "server_settings": {
                "application_name": "chat_cache_service"
            }
        }
    
    def get_openrouter_settings(self) -> dict:
        """Get OpenRouter API settings as a dictionary"""
        return {
            "api_url": self.openrouter_api_url,
            "api_key": self.openrouter_api_key,
            "model": self.openrouter_model,
            "service_name": self.chat_service_name,
            "service_url": self.chat_service_url
        }


# Global configuration instance
config = Configuration()



