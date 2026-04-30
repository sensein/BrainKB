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
Configuration settings for the BrainKB User Management Service.
"""

import os
from typing import Optional
from dotenv import load_dotenv


def load_environment(env_name="env"):
    """
    Load environment variables from the specified .env file.

    Args:
        env_name (str): Name of the environment (e.g., "production", "development").
                        Defaults to "env".

    Returns:
        dict: A dictionary containing the loaded environment variables.
    """
    # Determine the path to the .env file based on the environment
    # Always fall back to root .env file - service-specific .env files are removed
    core_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Traverse up to project root (BrainKB/)
    # usermanagement_service/core/ -> usermanagement_service/ -> BrainKB/
    project_root = os.path.dirname(os.path.dirname(core_dir))
    
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
        
        # JWT Configuration
        "JWT_ALGORITHM": os.getenv("JWT_ALGORITHM", "HS256"),
        "JWT_SECRET_KEY": os.getenv("USERMANAGEMENT_SERVICE_JWT_SECRET_KEY"),

        "JWT_BEARER_TOKEN_URL": os.getenv("JWT_BEARER_TOKEN_URL"),
        "JWT_LOGIN_EMAIL": os.getenv("JWT_LOGIN_EMAIL"),
        "JWT_LOGIN_PASSWORD": os.getenv("JWT_LOGIN_PASSWORD"),

        # OAuth / Admin Bootstrap
        "USERMANAGEMENT_PUBLIC_BASE_URL": os.getenv("USERMANAGEMENT_PUBLIC_BASE_URL", "http://localhost:8004"),
        "USERMANAGEMENT_FRONTEND_CALLBACK_URL": os.getenv("USERMANAGEMENT_FRONTEND_CALLBACK_URL", "http://localhost:3000/auth/callback"),
        "USERMANAGEMENT_OAUTH_TOKEN_ENC_KEY": os.getenv("USERMANAGEMENT_OAUTH_TOKEN_ENC_KEY"),
        # SuperAdmin bootstrap allowlist. Comma-separated emails. Seeded users
        # get the SuperAdmin + Admin roles on first sight; the SuperAdmin role
        # is protected against ban/delete/role-strip via the admin endpoints.
        "USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS": os.getenv("USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS", ""),

        "GITHUB_CLIENT_ID": os.getenv("GITHUB_CLIENT_ID"),
        "GITHUB_CLIENT_SECRET": os.getenv("GITHUB_CLIENT_SECRET"),

        "ORCID_CLIENT_ID": os.getenv("ORCID_CLIENT_ID"),
        "ORCID_CLIENT_SECRET": os.getenv("ORCID_CLIENT_SECRET"),
        "ORCID_BASE_URL": os.getenv("ORCID_BASE_URL", "https://orcid.org"),

        "GLOBUS_CLIENT_ID": os.getenv("GLOBUS_CLIENT_ID"),
        "GLOBUS_CLIENT_SECRET": os.getenv("GLOBUS_CLIENT_SECRET"),

        # Logging Configuration
        "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
        "LOG_FORMAT": os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
    }


class Configuration:
    """
    Centralized configuration class for the BrainKB User Management Service.
    Provides easy access to all environment variables with proper defaults.
    """
    
    def __init__(self, env_name: str = "env"):
        """
        Initialize configuration with environment variables.
        
        Args:
            env_name (str): Name of the environment file (e.g., "env", "production")
        """
        self._env_vars = load_environment(env_name)
    
    @property
    def env_state(self) -> Optional[str]:
        """Get the current environment state."""
        return self._env_vars.get("ENV_STATE")
    
    @property
    def postgres_host(self) -> Optional[str]:
        """Get the PostgreSQL host."""
        return self._env_vars.get("JWT_POSTGRES_DATABASE_HOST_URL")
    
    @property
    def postgres_port(self) -> Optional[str]:
        """Get the PostgreSQL port."""
        return self._env_vars.get("JWT_POSTGRES_DATABASE_PORT")
    
    @property
    def postgres_user(self) -> Optional[str]:
        """Get the PostgreSQL user."""
        return self._env_vars.get("JWT_POSTGRES_DATABASE_USER")
    
    @property
    def postgres_password(self) -> Optional[str]:
        """Get the PostgreSQL password."""
        return self._env_vars.get("JWT_POSTGRES_DATABASE_PASSWORD")
    
    @property
    def postgres_database(self) -> Optional[str]:
        """Get the PostgreSQL database name."""
        return self._env_vars.get("JWT_POSTGRES_DATABASE_NAME")
    
    @property
    def jwt_algorithm(self) -> str:
        """Get the JWT algorithm."""
        return self._env_vars.get("JWT_ALGORITHM", "HS256")
    
    @property
    def jwt_secret_key(self) -> Optional[str]:
        """Get the JWT secret key."""
        return self._env_vars.get("JWT_SECRET_KEY")
    
    @property
    def jwt_bearer_token_url(self) -> str:
        """Get the JWT bearer token URL."""
        return self._env_vars.get("JWT_BEARER_TOKEN_URL", "")
    
    @property
    def jwt_login_username(self) -> str:
        """Get the JWT login username."""
        return self._env_vars.get("JWT_LOGIN_EMAIL", "")
    
    @property
    def jwt_login_password(self) -> str:
        """Get the JWT login password."""
        return self._env_vars.get("JWT_LOGIN_PASSWORD", "")
    
    @property
    def log_level(self) -> str:
        """Get the log level."""
        return self._env_vars.get("LOG_LEVEL", "INFO")
    
    @property
    def log_format(self) -> str:
        """Get the log format."""
        return self._env_vars.get("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    
    @property
    def logtail_api_key(self) -> Optional[str]:
        """Get the Logtail API key."""
        return self._env_vars.get("LOGTAIL_API_KEY")
    
    @property
    def public_base_url(self) -> str:
        return self._env_vars.get("USERMANAGEMENT_PUBLIC_BASE_URL", "http://localhost:8004")

    @property
    def frontend_callback_url(self) -> str:
        return self._env_vars.get("USERMANAGEMENT_FRONTEND_CALLBACK_URL", "http://localhost:3000/auth/callback")

    @property
    def oauth_token_enc_key(self) -> Optional[str]:
        return self._env_vars.get("USERMANAGEMENT_OAUTH_TOKEN_ENC_KEY")

    @property
    def bootstrap_superadmin_emails(self) -> list:
        """Emails that get seeded as SuperAdmin (and Admin) on startup / first
        OAuth login. Read from USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS."""
        raw = self._env_vars.get("USERMANAGEMENT_BOOTSTRAP_SUPERADMIN_EMAILS", "") or ""
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    @property
    def github_client_id(self) -> Optional[str]:
        return self._env_vars.get("GITHUB_CLIENT_ID")

    @property
    def github_client_secret(self) -> Optional[str]:
        return self._env_vars.get("GITHUB_CLIENT_SECRET")

    @property
    def orcid_client_id(self) -> Optional[str]:
        return self._env_vars.get("ORCID_CLIENT_ID")

    @property
    def orcid_client_secret(self) -> Optional[str]:
        return self._env_vars.get("ORCID_CLIENT_SECRET")

    @property
    def orcid_base_url(self) -> str:
        return self._env_vars.get("ORCID_BASE_URL", "https://orcid.org")

    @property
    def globus_client_id(self) -> Optional[str]:
        return self._env_vars.get("GLOBUS_CLIENT_ID")

    @property
    def globus_client_secret(self) -> Optional[str]:
        return self._env_vars.get("GLOBUS_CLIENT_SECRET")

    def get_postgres_settings(self) -> dict:
        """
        Get PostgreSQL settings as a dictionary.
        
        Returns:
            dict: PostgreSQL configuration settings
        """
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "user": self.postgres_user,
            "password": self.postgres_password,
            "database": self.postgres_database,
        }


# Global configuration instance
config = Configuration()



