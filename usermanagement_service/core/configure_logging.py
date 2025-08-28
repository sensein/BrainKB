# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with
# the software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : configure_logging.py
# @Software: PyCharm

import logging
import os
from logging.handlers import RotatingFileHandler
from logging import StreamHandler

from asgi_correlation_id import CorrelationIdFilter
from core.configuration import config


def configure_logging():
    """Configure logging based on environment state"""
    
    # Create logs directory if it doesn't exist
    logs_dir = "logs"
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        print(f"Created logs directory: {logs_dir}")
    
    if config.env_state == "prod":
        # Production logging configuration
        logging.basicConfig(
            level=logging.INFO,
            format=config.log_format,
            handlers=[
                RotatingFileHandler(
                    "logs/app.log",
                    maxBytes=10 * 1024 * 1024,  # 10MB
                    backupCount=5
                ),
                # Note: LogtailHandler would need to be imported from logtail package
                # For now, we'll use a basic handler
                StreamHandler()
            ]
        )
    else:
        # Development logging configuration
        logging.basicConfig(
            level=logging.DEBUG,
            format=config.log_format,
            handlers=[
                StreamHandler(),
                RotatingFileHandler(
                    "logs/app.log",
                    maxBytes=10 * 1024 * 1024,  # 10MB
                    backupCount=5
                )
            ]
        )
    
    # Configure specific loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("fastapi").setLevel(logging.INFO)
    
    # Set correlation ID filter
    logging.getLogger().addFilter(CorrelationIdFilter())
    
    return logging.getLogger(__name__)
