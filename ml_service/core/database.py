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
# @File    : database.py
# @Software: PyCharm
from datetime import datetime
import logging
import asyncpg
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from fastapi import HTTPException, status

from core.configuration import load_environment

logger = logging.getLogger(__name__)

DB_SETTINGS = {
    "user": load_environment()["JWT_POSTGRES_DATABASE_USER"],
    "password": load_environment()["JWT_POSTGRES_DATABASE_PASSWORD"],
    "database": load_environment()["JWT_POSTGRES_DATABASE_NAME"],
    "host": load_environment()["JWT_POSTGRES_DATABASE_HOST_URL"],
    "port": load_environment()["JWT_POSTGRES_DATABASE_PORT"],
}

table_name_user = load_environment()["JWT_POSTGRES_TABLE_USER"]
table_name_scope = load_environment()["JWT_POSTGRES_TABLE_SCOPE"]
table_relation = load_environment()["JWT_POSTGRES_TABLE_USER_SCOPE_REL"]

# Global connection pool
pool = None

async def init_db_pool():
    """Initialize the database connection pool."""
    import os
    global pool
    
    # CRITICAL: Print to track pool instances
    print("=" * 80)
    print(f"[DB POOL INIT] Process ID: {os.getpid()}")
    print(f"[DB POOL INIT] Pool instance before: {id(pool) if pool is not None else 'None'}")
    
    if pool is not None:
        print(f"[DB POOL INIT] WARNING: Pool already exists! Instance ID: {id(pool)}")
        print("=" * 80)
        return pool
    
    print(f"[DB POOL INIT] Creating NEW pool instance...")
    
    try:
        env_state = load_environment().get("ENV_STATE", "production").lower()
        
        # CRITICAL FIX: Account for multiple workers
        # Gunicorn workers: each creates its own pool
        num_workers = int(os.getenv("WEB_CONCURRENCY", "1" if env_state == "development" else "4"))
        
        # Calculate per-worker sizes to avoid exceeding PostgreSQL limits
        # Increased pool size to handle high concurrent JWT token requests
        # After optimization: each token request uses 1 connection (was 2)
        # Target: support 100+ concurrent requests safely
        if env_state == "development":
            min_size = 0  # Lazy init - no connections at startup
            max_size = 10
        else:
            min_size = 2  # Keep a few connections ready for fast JWT validation
            # Calculate pool size to support high concurrency
            # Target: 100+ concurrent requests across all workers
            # Formula: ensure at least 20-30 connections per worker, but cap at reasonable limit
            # Allow environment override via DB_POOL_MAX_SIZE
            if os.getenv("DB_POOL_MAX_SIZE"):
                max_size = int(os.getenv("DB_POOL_MAX_SIZE"))
            else:
                # Default: 25 per worker (supports 100 concurrent with 4 workers, 150 with 6)
                # PostgreSQL default max_connections is usually 100, but can be increased
                max_size = 25
        
        print(f"[DB POOL INIT] Workers: {num_workers}, min={min_size}, max={max_size} per worker")
        print(f"[DB POOL INIT] Total potential: {max_size * num_workers} connections")

        pool = await asyncpg.create_pool(
            min_size=min_size,
            max_size=max_size,
            max_inactive_connection_lifetime=300,
            command_timeout=60,
            **DB_SETTINGS
        )
        print(f"[DB POOL INIT] Pool created! Instance ID: {id(pool)}")
        print("=" * 80)
        logger.info(f"Database connection pool initialized (workers={num_workers}, min={min_size}, max={max_size} per worker)")
        return pool
    except Exception as e:
        print(f"[DB POOL INIT] ERROR: {str(e)}")
        print("=" * 80)
        logger.error(f"Failed to initialize database connection pool: {str(e)}")
        raise

async def get_db_pool():
    """Get the database connection pool. Initialize if not already done."""
    import os
    global pool
    
    print(f"[GET DB POOL] Process ID: {os.getpid()}, Pool: {id(pool) if pool is not None else 'None'}")
    
    if pool is None:
        pool = await init_db_pool()
    return pool

@asynccontextmanager
async def get_db_connection():
    """
    Context manager for database connections.
    
    IMPORTANT: 
    - The POOL stays alive for the entire application lifetime (not closed after each request)
    - Individual CONNECTIONS are acquired per request and released back to the pool
    - This is efficient: pool is created once, connections are reused
    
    Usage:
        async with get_db_connection() as conn:
            result = await conn.fetch("SELECT * FROM table")
    """
    import os
    import asyncio
    pool = await get_db_pool()
    
    # Get pool status before acquiring
    pool_size = pool.get_size()
    idle_size = pool.get_idle_size()
    in_use = pool_size - idle_size
    
    print(f"[CONN ACQUIRE] Process {os.getpid()}: Acquiring connection... (pool: size={pool_size}, idle={idle_size}, in_use={in_use})")
    
    # Add timeout to prevent indefinite waiting
    # Increased timeout to 30s to handle temporary pool exhaustion during bursts
    try:
        conn = await asyncio.wait_for(pool.acquire(), timeout=30.0)
        print(f"[CONN ACQUIRE] Connection acquired! (pool now: size={pool.get_size()}, idle={pool.get_idle_size()}, in_use={pool.get_size() - pool.get_idle_size()})")
    except asyncio.TimeoutError:
        logger.error("Connection acquisition timed out after 30 seconds")
        raise HTTPException(
            status_code=503,
            detail="Database connection timeout. Please try again."
        )
    except asyncpg.exceptions.TooManyConnectionsError as e:
        logger.error(f"Too many database connections: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail="Database temporarily unavailable due to connection limit. Please try again in a moment."
        )
    
    try:
        yield conn
    finally:
        # Always release connection back to pool (not closed, just returned to pool)
        await pool.release(conn)
        pool_size_after = pool.get_size()
        idle_size_after = pool.get_idle_size()
        print(f"[CONN RELEASE] Connection released back to pool! (pool now: size={pool_size_after}, idle={idle_size_after}, in_use={pool_size_after - idle_size_after})")

# FastAPI dependency for automatic connection management in routes
async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """FastAPI dependency for database connections."""
    async with get_db_connection() as conn:
        yield conn

# Deprecated - kept for backward compatibility
async def connect_postgres():
    """
    DEPRECATED: Use get_db_connection() context manager instead.
    Get a connection from the pool.
    """
    try:
        pool = await get_db_pool()
        return await pool.acquire()
    except Exception as e:
        logger.error(f"Failed to acquire connection from pool: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# Deprecated - kept for backward compatibility
async def close_db_connection(conn):
    """
    DEPRECATED: Use get_db_connection() context manager instead.
    Release a connection back to the pool.
    """
    try:
        pool = await get_db_pool()
        await pool.release(conn)
    except Exception as e:
        logger.error(f"Failed to release connection to pool: {str(e)}")

async def debug_pool_status():
    """Debug helper to check pool status."""
    if pool:
        logger.info(f"Pool size: {pool.get_size()}")
        logger.info(f"Free connections: {pool.get_idle_size()}")
        logger.info(f"Used connections: {pool.get_size() - pool.get_idle_size()}")

# ============================================================================
# Refactored Database Functions - Using Context Manager Pattern
# ============================================================================

async def insert_data(fullname: str, email: str, password: str, conn: Optional[asyncpg.Connection] = None):
    """
    Insert a new user with default 'read' scope.
    If conn is provided, uses that connection (caller manages it).
    Otherwise, manages its own connection.
    """
    async def _insert_logic(connection):
        # Use a transaction to ensure all operations succeed or fail together
        async with connection.transaction():
            scope_exist_id = await select_scope_id(connection)

            if not scope_exist_id:
                # First insert the default read access
                scope_query = f"""
                INSERT INTO \"{table_name_scope}\" (name, description, created_at, updated_at) 
                VALUES ($1, $2, $3, $4) RETURNING id"""

                new_scope_id = await connection.fetchval(
                    scope_query,
                    "read",
                    "This allows read access",
                    datetime.utcnow(),
                    datetime.utcnow(),
                )

                user_query = f"""
                    INSERT INTO \"{table_name_user}\" (full_name, email, password, is_active, created_at, updated_at) 
                    VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """
                jwt_user_id = await connection.fetchval(
                    user_query,
                    fullname,
                    email,
                    password,
                    False,
                    datetime.utcnow(),
                    datetime.utcnow(),
                )

                # Connect with relationship
                await connection.execute(
                    f"""INSERT INTO \"{table_relation}\" (jwtuser_id, scope_id) VALUES ($1, $2)""",
                    jwt_user_id,
                    new_scope_id,
                )
            else:
                user_query = f"""
                    INSERT INTO \"{table_name_user}\" (full_name, email, password, is_active, created_at, updated_at) 
                    VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """
                jwt_user_id = await connection.fetchval(
                    user_query,
                    fullname,
                    email,
                    password,
                    False,
                    datetime.utcnow(),
                    datetime.utcnow(),
                )

                await connection.execute(
                    f"""INSERT INTO \"{table_relation}\" (jwtuser_id, scope_id) VALUES ($1, $2)""",
                    jwt_user_id,
                    scope_exist_id,
                )

        return {
            "detail": "Registration completed successfully! Admin will activate your account after verification."
        }

    try:
        if conn is not None:
            # Use provided connection
            return await _insert_logic(conn)
        else:
            # Manage our own connection
            async with get_db_connection() as connection:
                return await _insert_logic(connection)
    except asyncpg.exceptions.UniqueViolationError as e:
        # Handle unique constraint violations (e.g., duplicate email) atomically
        logger.warning(f"Registration attempt with duplicate email {email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with that email already exists"
        )
    except Exception as e:
        logger.error(f"Error inserting data for user {email}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


async def insert_scope(conn: Optional[asyncpg.Connection] = None):
    """
    Check if 'read' scope exists.
    Returns the scope row if it exists, False otherwise.
    """
    query = f"SELECT id FROM \"{table_name_scope}\" WHERE name = 'read'"

    try:
        if conn is not None:
            # Use provided connection
            row = await conn.fetchrow(query)
            return row if row else False
        else:
            # Manage our own connection
            async with get_db_connection() as connection:
                row = await connection.fetchrow(query)
                return row if row else False
    except Exception as e:
        logger.error(f"Error checking scope: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


async def select_scope_id(conn: Optional[asyncpg.Connection] = None) -> Optional[int]:
    """
    Get the ID of the 'read' scope.
    Returns the scope ID if found, None otherwise.
    """
    query = f"SELECT id FROM \"{table_name_scope}\" WHERE name = 'read' LIMIT 1;"

    try:
        if conn is not None:
            # Use provided connection
            scope_id = await conn.fetchval(query)
            logger.debug(f"Selected scope ID: {scope_id}")
            return scope_id
        else:
            # Manage our own connection
            async with get_db_connection() as connection:
                scope_id = await connection.fetchval(query)
                logger.debug(f"Selected scope ID: {scope_id}")
                return scope_id
    except Exception as e:
        logger.error(f"Error selecting scope ID: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


async def get_scopes_by_user(user_id: int, conn: Optional[asyncpg.Connection] = None):
    """
    Get all scope names assigned to a user.
    Returns a list of scope names.
    If conn is provided, uses that connection (caller manages it).
    Otherwise, manages its own connection.
    """
    query = f"""
    SELECT s.name
    FROM \"{table_name_scope}\" s
    JOIN \"{table_relation}\" js ON s.id = js.scope_id
    WHERE js.jwtuser_id = $1
    """

    try:
        if conn is not None:
            # Use provided connection
            results = await conn.fetch(query, user_id)
            assigned_scopes_to_user = [result["name"] for result in results]
            logger.debug(f"Scopes for user {user_id}: {assigned_scopes_to_user}")
            return assigned_scopes_to_user
        else:
            # Manage our own connection
            async with get_db_connection() as connection:
                results = await connection.fetch(query, user_id)
                assigned_scopes_to_user = [result["name"] for result in results]
                logger.debug(f"Scopes for user {user_id}: {assigned_scopes_to_user}")
                return assigned_scopes_to_user
    except Exception as e:
        logger.error(f"Error getting scopes for user {user_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


async def get_user(email: str, conn: Optional[asyncpg.Connection] = None):
    """
    Get an active user by email.
    Returns the user row if found and active, False otherwise.
    """
    query = f"""
    SELECT * FROM \"{table_name_user}\" 
    WHERE email = $1 AND is_active = True 
    LIMIT 1
    """

    try:
        if conn is not None:
            # Use provided connection
            row = await conn.fetchrow(query, email)
            return row if row else False
        else:
            # Manage our own connection
            async with get_db_connection() as connection:
                row = await connection.fetchrow(query, email)
                return row if row else False
    except Exception as e:
        logger.error(f"Error getting user with email {email}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))