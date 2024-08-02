from logging.config import dictConfig

from brain2kg.api.configuration import load_environment

print(load_environment())
handlers = ["default", "rotating_file"]
if load_environment()["ENV_STATE"] == "prod":
    handlers = [
        "default",
        "rotating_file",
        "logtail",
    ]  # if we don't want to store logs in logtail then it can be removed


def configure_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "correlation_id": {
                    "()": "asgi_correlation_id.CorrelationIdFilter",
                    "uuid_length": (
                        8 if load_environment()["ENV_STATE"] == "dev" else 32
                    ),
                    "default_value": "-",
                },
            },
            "formatters": {
                "console": {
                    "class": "logging.Formatter",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                    "format": "(%(correlation_id)s) %(name)s:%(lineno)d - %(message)s",
                },
                "file": {
                    "class": "pythonjsonlogger.jsonlogger.JsonFormatter",
                    "datefmt": "%Y-%m-%dT%H:%M:%S",
                    "format": "%(asctime)s %(msecs)03d %(levelname)s %(correlation_id)s %(name)s %(lineno)d %(message)s",
                },
            },
            "handlers": {
                "default": {
                    "class": "rich.logging.RichHandler",
                    "level": "DEBUG",
                    "formatter": "console",
                    "filters": ["correlation_id"],
                },
                "logtail": {
                    "class": "logtail.LogtailHandler",
                    "level": "DEBUG",
                    "formatter": "console",
                    "filters": ["correlation_id"],
                    "source_token": load_environment()["LOGTAIL_API_KEY"],
                },
                "rotating_file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "level": "DEBUG",
                    "formatter": "file",
                    "filters": ["correlation_id"],
                    "filename": "fastapi.log",
                    "maxBytes": 1024 * 1024 * 40,  # 40 MB each file
                    "backupCount": 2,  # total number of files you want to keep after that the file will be deleted
                    "encoding": "utf8",
                },
            },
            "loggers": {
                "uvicorn": {
                    "handlers": ["default", "rotating_file", "logtail"],
                    "level": "INFO",
                },
                "apiinfo": {
                    "handlers": handlers,
                    "level": (
                        "DEBUG" if load_environment()["ENV_STATE"] == "dev" else "INFO"
                    ),
                    "propogate": False,
                },
                "databases": {
                    "handlers": ["default"],
                    "level": "WARNING",
                },
                "aiosqlite": {
                    "handlers": ["default"],
                    "level": "WARNING",
                },
            },
        }
    )