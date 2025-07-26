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
from datetime import datetime
import logging

# @Author  : Tek Raj Chhetri
# @Email   : tekraj@mit.edu
# @Web     : https://tekrajchhetri.com/
# @File    : database.py
# @Software: PyCharm
import asyncpg
from fastapi import HTTPException

from core.configuration import config

logger = logging.getLogger(__name__)

# Database settings
database_settings = {
    "user": config.postgres_user,
    "password": config.postgres_password,
    "database": config.postgres_database,
    "host": config.postgres_host,
    "port": config.postgres_port,
}

table_name_user = config.postgres_table_user
table_name_scope = config.postgres_table_scope
table_relation = config.postgres_table_user_scope_rel

# Global connection pool
pool = None

async def init_db_pool():
    """Initialize the database connection pool."""
    global pool
    try:
        # Create a connection pool with min_size=10 and max_size=100 to handle high concurrency
        pool = await asyncpg.create_pool(
            min_size=10,
            max_size=100,
            **database_settings
        )
        logger.info("Database connection pool initialized")
        return pool
    except Exception as e:
        logger.error(f"Failed to initialize database connection pool: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database connection error: {str(e)}")

async def get_db_pool():
    """Get the database connection pool. Initialize if not already done."""
    global pool
    if pool is None:
        pool = await init_db_pool()
    return pool

async def connect_postgres():
    """Get a connection from the pool."""
    try:
        pool = await get_db_pool()
        return await pool.acquire()
    except Exception as e:
        logger.error(f"Failed to acquire connection from pool: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def close_db_connection(conn):
    """Release a connection back to the pool."""
    try:
        pool = await get_db_pool()
        await pool.release(conn)
    except Exception as e:
        logger.error(f"Failed to release connection to pool: {str(e)}")


async def insert_data(conn=None, fullname=None, email=None, password=None):
    connection_created = False
    try:
        if conn is None:
            conn = await connect_postgres()
            connection_created = True
        
        # Use a transaction to ensure all operations succeed or fail together
        async with conn.transaction():
            scope_exist_id = await select_scope_id(conn)
            if not scope_exist_id:
                # First insert the default read access
                scope_query_exist_case = f"""
                INSERT INTO \"{table_name_scope}\" (name, description, created_at, updated_at) 
                VALUES ($1, $2, $3, $4) RETURNING id"""

                new_scope_id = await conn.fetchval(
                    scope_query_exist_case,
                    "read",
                    "This allows read access",
                    datetime.utcnow(),
                    datetime.utcnow(),
                )
                pg_query = f"""
                    INSERT INTO \"{table_name_user}\" (full_name, email, password, is_active, created_at, updated_at) 
                    VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """
                jwt_user_id = await conn.fetchval(
                    pg_query,
                    fullname,
                    email,
                    password,
                    False,
                    datetime.utcnow(),
                    datetime.utcnow(),
                )

                # now connect with rel
                await conn.execute(
                    f"""INSERT INTO \"{table_relation}\" (jwtuser_id, scope_id) VALUES ($1, $2)""",
                    jwt_user_id,
                    new_scope_id,
                )
            else:
                pg_query = f"""
                    INSERT INTO \"{table_name_user}\" (full_name, email, password, is_active, created_at, updated_at) 
                    VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
                """
                jwt_user_id = await conn.fetchval(
                    pg_query,
                    fullname,
                    email,
                    password,
                    False,
                    datetime.utcnow(),
                    datetime.utcnow(),
                )

                await conn.execute(
                    f"""INSERT INTO \"{table_relation}\" (jwtuser_id, scope_id) VALUES ($1, $2)""",
                    jwt_user_id,
                    scope_exist_id,
                )

        return {
            "detail": "Registration completed successfully! Admin will activate your account after verification."
        }
    except Exception as e:
        logger.error(f"Error inserting data for user {email}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Only release the connection if we created it in this function
        if connection_created and conn:
            await close_db_connection(conn)


async def insert_scope(conn=None):
    connection_created = False
    try:
        if conn is None:
            conn = await connect_postgres()
            connection_created = True
            query = f"SELECT id FROM \"{table_name_scope}\" WHERE NAME = 'read'"
        row = await conn.fetchrow(
            query
        )
        if row:
            return row
        return False
    except Exception as e:
        logger.error(f"Error inserting scope: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Only release the connection if we created it in this function
        if connection_created and conn:
            await close_db_connection(conn)


async def select_scope_id(conn=None):
    connection_created = False
    try:
        if conn is None:
            conn = await connect_postgres()
            connection_created = True
        
        query = f"SELECT id FROM \"{table_name_scope}\" WHERE NAME = 'read' LIMIT 1;"
        scope_id = await conn.fetchval(query)
        logger.debug(f"Selected scope ID: {scope_id}")
        return scope_id  # Returns the user ID if found, or None if no user exists
    except Exception as e:
        logger.error(f"Error selecting scope ID: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Only release the connection if we created it in this function
        if connection_created and conn:
            await close_db_connection(conn)


async def get_scopes_by_user(user_id):
    conn = await connect_postgres()
    query = f"""SELECT s.name
    FROM \"{table_name_scope}\" s
    JOIN \"{table_relation}\" js ON s.id = js.scope_id
    WHERE js.jwtuser_id =  $1"""
    try:
        results = await conn.fetch(query, user_id)
        assigned_scopes_to_user = [result["name"] for result in results]
        logger.debug(f"Scopes for user {user_id}: {assigned_scopes_to_user}")
        return assigned_scopes_to_user
    except Exception as e:
        logger.error(f"Error getting scopes for user {user_id}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Release the connection back to the pool
        await close_db_connection(conn)


async def get_user(conn=None, email=None):
    connection_created = False
    try:
        if conn is None:
            conn = await connect_postgres()
            connection_created = True
        
        query = """
        SELECT * FROM "{}" WHERE email = $1 AND is_active=True LIMIT 1
        """.format(
            table_name_user
        )
        row = await conn.fetchrow(query, email)
        if row:
            return row
        return False
    except Exception as e:
        logger.error(f"Error getting user with email {email}: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Only release the connection if we created it in this function
        if connection_created and conn:
            await close_db_connection(conn)
