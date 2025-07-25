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
# @File    : postgres_cache.py
# @Software: PyCharm

import logging
import asyncpg
from fastapi import HTTPException
from core.configuration import load_environment
from core.models.postgres_cache import PostgresChatCache

logger = logging.getLogger(__name__)

# Global PostgreSQL cache pool
postgres_cache_pool = None

def get_postgres_cache_settings():
    """Get PostgreSQL cache database settings from environment"""
    env = load_environment()
    return {
        "host": env["JWT_POSTGRES_DATABASE_HOST_URL"],
        "port": env["JWT_POSTGRES_DATABASE_PORT"],
        "user": env["JWT_POSTGRES_DATABASE_USER"],
        "password": env["JWT_POSTGRES_DATABASE_PASSWORD"],
        "database": env["JWT_POSTGRES_DATABASE_NAME"],
        "min_size": 10,
        "max_size": 100,
        "command_timeout": 60,
        "server_settings": {
            "application_name": "chat_cache_service"
        }
    }

async def init_postgres_cache_pool():
    """Initialize the PostgreSQL cache connection pool"""
    global postgres_cache_pool
    try:
        settings = get_postgres_cache_settings()
        
        # Create connection pool
        postgres_cache_pool = await asyncpg.create_pool(**settings)
        logger.info("PostgreSQL cache connection pool initialized")
        
        # Initialize cache table
        cache = PostgresChatCache(postgres_cache_pool)
        await cache.create_cache_table()
        
        return postgres_cache_pool
        
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL cache connection pool: {str(e)}")
        raise HTTPException(status_code=500, detail=f"PostgreSQL cache connection error: {str(e)}")

async def get_postgres_cache_pool():
    """Get the PostgreSQL cache connection pool. Initialize if not already done."""
    global postgres_cache_pool
    if postgres_cache_pool is None:
        postgres_cache_pool = await init_postgres_cache_pool()
    return postgres_cache_pool

async def get_cache_instance():
    """Get a PostgresChatCache instance"""
    pool = await get_postgres_cache_pool()
    return PostgresChatCache(pool)

async def close_postgres_cache_pool():
    """Close the PostgreSQL cache connection pool"""
    global postgres_cache_pool
    if postgres_cache_pool:
        await postgres_cache_pool.close()
        logger.info("PostgreSQL cache connection pool closed")
        postgres_cache_pool = None 