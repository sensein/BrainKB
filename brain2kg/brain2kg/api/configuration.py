import os

from dotenv import load_dotenv


def load_environment(env_name="development"):
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
    env_file = os.path.join(root_dir, f".env.{env_name}")

    # Load environment variables from the .env.development.development file
    load_dotenv(dotenv_path=env_file)

    # Return a dictionary containing the loaded environment variables
    return {
        "ENV_STATE": os.getenv("ENV_STATE"),
        "DATABASE_URL": os.getenv("DATABASE_URL"),
        "LOGTAIL_API_KEY": os.getenv("LOGTAIL_API_KEY"),
        "POSTGRES_SERVER": os.getenv("POSTGRES_SERVER"),
        "POSTGRES_PORT": os.getenv("POSTGRES_PORT"),
        "POSTGRES_USER": os.getenv("POSTGRES_USER"),
        "JWT_POSTGRES_TABLE_USER": os.getenv("JWT_POSTGRES_TABLE_USER", "Web_jwtuser"),
        "JWT_POSTGRES_TABLE_SCOPE": os.getenv("JWT_POSTGRES_TABLE_SCOPE", "Web_scope"),
        "JWT_POSTGRES_TABLE_USER_SCOPE_REL": os.getenv(
            "JWT_POSTGRES_TABLE_USER_SCOPE_REL", "Web_jwtuser_scopes"
        ),
        "POSTGRES_PASSWORD": os.getenv("POSTGRES_PASSWORD"),
        "POSTGRES_DB": os.getenv("POSTGRES_DB"),
        "JWT_ALGORITHM": os.getenv("JWT_ALGORITHM", "HS256"),
        "JWT_SECRET_KEY": os.getenv("JWT_SECRET_KEY"),

        # service specific
        "GRAPHDATABASE_USERNAME": os.getenv("GRAPHDATABASE_USERNAME"),
        "GRAPHDATABASE_PASSWORD": os.getenv("GRAPHDATABASE_PASSWORD"),
        "GRAPHDATABASE_HOSTNAME": os.getenv("GRAPHDATABASE_HOSTNAME", "http://localhost"),
        "GRAPHDATABASE_PORT": os.getenv("GRAPHDATABASE_HOSTNAME", 7200),
        "GRAPHDATABASE_TYPE": os.getenv("GRAPHDATABASE_TYPE", "GRAPHDB"),
        "GRAPHDATABASE_REPOSITORY": os.getenv("GRAPHDATABASE_REPOSITORY")
    }


if __name__ == "__main__":
    print(load_environment())