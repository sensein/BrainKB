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

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import asyncpg
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class CacheEntry:
    """Represents a cache entry in the database"""
    
    def __init__(self, cache_key: str, cache_value: str, ttl: int = 3600, 
                 created_at: Optional[datetime] = None, accessed_at: Optional[datetime] = None,
                 hit_count: int = 0):
        self.cache_key = cache_key
        self.cache_value = cache_value
        self.ttl = ttl  # Time to live in seconds
        self.created_at = created_at or datetime.utcnow()
        self.accessed_at = accessed_at or datetime.utcnow()
        self.hit_count = hit_count
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'cache_key': self.cache_key,
            'cache_value': self.cache_value,
            'ttl': self.ttl,
            'created_at': self.created_at,
            'accessed_at': self.accessed_at,
            'hit_count': self.hit_count
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheEntry':
        return cls(
            cache_key=data['cache_key'],
            cache_value=data['cache_value'],
            ttl=data['ttl'],
            created_at=data['created_at'],
            accessed_at=data['accessed_at'],
            hit_count=data.get('hit_count', 0)
        )

class PostgresChatCache:
    """PostgreSQL-based caching system for chat responses"""
    
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
    
    async def create_cache_table(self):
        """Create the cache table if it doesn't exist"""
        async with self.pool.acquire() as conn:
            try:
                # First check if table exists
                check_table_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'chat_cache'
                );
                """
                table_exists = await conn.fetchval(check_table_query)
                
                if not table_exists:
                    # Create cache table with PostgreSQL-specific optimizations
                    create_table_sql = """
                    CREATE TABLE chat_cache (
                        id BIGSERIAL PRIMARY KEY,
                        cache_key VARCHAR(64) NOT NULL UNIQUE,
                        cache_value TEXT NOT NULL,
                        ttl INTEGER DEFAULT 3600,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        accessed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        hit_count INTEGER DEFAULT 0,
                        last_hit TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                        metadata JSONB DEFAULT '{}'::jsonb
                    );
                    """
                    await conn.execute(create_table_sql)
                    logger.info("PostgreSQL cache table created")
                    
                    # Create indexes after table creation
                    create_indexes_sql = """
                    CREATE INDEX idx_cache_key ON chat_cache (cache_key);
                    CREATE INDEX idx_created_at_ttl ON chat_cache (created_at, ttl);
                    CREATE INDEX idx_hit_count ON chat_cache (hit_count DESC);
                    CREATE INDEX idx_last_hit ON chat_cache (last_hit DESC);
                    CREATE INDEX idx_metadata ON chat_cache USING GIN (metadata);
                    """
                    await conn.execute(create_indexes_sql)
                    logger.info("PostgreSQL cache indexes created")
                else:
                    logger.info("PostgreSQL cache table already exists")
                    
            except Exception as e:
                logger.error(f"Error creating cache table: {str(e)}")
                # Continue without cache if table creation fails
                pass
    
    def generate_cache_key(self, message: str, context: Dict[str, Any] = None, 
                          session_id: str = None) -> str:
        """Generate a unique cache key based on message and context (excluding session_id for cross-user caching)"""
        # Create a hashable string from the input (excluding session_id for shared caching)
        cache_data = {
            'message': message.lower().strip(),
            'context': context or {}
            # Removed session_id to enable cross-user caching
        }
        
        # Convert to JSON string and hash it
        cache_string = json.dumps(cache_data, sort_keys=True)
        # Use SHA256 and take first 32 characters for fixed length
        return hashlib.sha256(cache_string.encode()).hexdigest()[:32]
    
    async def get(self, cache_key: str) -> Optional[CacheEntry]:
        """Retrieve a cache entry by key"""
        try:
            async with self.pool.acquire() as conn:
                # Check if cache entry exists and is not expired
                query = """
                SELECT cache_key, cache_value, ttl, created_at, accessed_at, hit_count, last_hit, metadata
                FROM chat_cache 
                WHERE cache_key = $1 
                AND created_at > (NOW() - INTERVAL '1 second' * ttl)
                """
                row = await conn.fetchrow(query, cache_key)
                
                if row:
                    # Update hit statistics
                    update_query = """
                    UPDATE chat_cache 
                    SET accessed_at = NOW(), 
                        hit_count = hit_count + 1,
                        last_hit = NOW()
                    WHERE cache_key = $1
                    """
                    await conn.execute(update_query, cache_key)
                    
                    return CacheEntry(
                        cache_key=row['cache_key'],
                        cache_value=row['cache_value'],
                        ttl=row['ttl'],
                        created_at=row['created_at'],
                        accessed_at=row['accessed_at'],
                        hit_count=row['hit_count'] + 1
                    )
                
                return None
                
        except Exception as e:
            logger.error(f"Error retrieving cache entry: {str(e)}")
            return None
    
    async def set(self, cache_key: str, cache_value: str, ttl: int = 3600, 
                  metadata: Dict[str, Any] = None) -> bool:
        """Store a cache entry"""
        try:
            async with self.pool.acquire() as conn:
                # Use PostgreSQL's UPSERT (INSERT ... ON CONFLICT)
                query = """
                INSERT INTO chat_cache (cache_key, cache_value, ttl, created_at, accessed_at, hit_count, last_hit, metadata)
                VALUES ($1, $2, $3, NOW(), NOW(), 0, NOW(), $4)
                ON CONFLICT (cache_key) DO UPDATE SET
                    cache_value = EXCLUDED.cache_value,
                    ttl = EXCLUDED.ttl,
                    accessed_at = NOW(),
                    hit_count = 0,
                    last_hit = NOW(),
                    metadata = EXCLUDED.metadata
                """
                await conn.execute(query, cache_key, cache_value, ttl, json.dumps(metadata or {}))
                return True
                
        except Exception as e:
            logger.error(f"Error storing cache entry: {str(e)}")
            return False
    
    async def delete(self, cache_key: str) -> bool:
        """Delete a cache entry"""
        try:
            async with self.pool.acquire() as conn:
                query = "DELETE FROM chat_cache WHERE cache_key = $1"
                result = await conn.execute(query, cache_key)
                return result != "DELETE 0"
                
        except Exception as e:
            logger.error(f"Error deleting cache entry: {str(e)}")
            return False
    
    async def clear_expired(self) -> int:
        """Clear expired cache entries and return count of deleted entries"""
        try:
            async with self.pool.acquire() as conn:
                query = """
                DELETE FROM chat_cache 
                WHERE created_at < (NOW() - INTERVAL '1 second' * ttl)
                """
                result = await conn.execute(query)
                # Parse the result to get count
                deleted_count = int(result.split()[-1]) if result.startswith("DELETE") else 0
                logger.info(f"Cleared {deleted_count} expired cache entries")
                return deleted_count
                
        except Exception as e:
            logger.error(f"Error clearing expired cache entries: {str(e)}")
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            async with self.pool.acquire() as conn:
                # Get comprehensive cache statistics
                queries = {
                    'total_entries': "SELECT COUNT(*) as count FROM chat_cache",
                    'active_entries': """
                        SELECT COUNT(*) as count 
                        FROM chat_cache 
                        WHERE created_at > (NOW() - INTERVAL '1 second' * ttl)
                    """,
                    'expired_entries': """
                        SELECT COUNT(*) as count 
                        FROM chat_cache 
                        WHERE created_at <= (NOW() - INTERVAL '1 second' * ttl)
                    """,
                    'total_hits': "SELECT COALESCE(SUM(hit_count), 0) as count FROM chat_cache",
                    'avg_hits': "SELECT COALESCE(AVG(hit_count), 0) as count FROM chat_cache",
                    'top_cached': """
                        SELECT cache_key, hit_count, created_at, last_hit
                        FROM chat_cache 
                        ORDER BY hit_count DESC 
                        LIMIT 10
                    """,
                    'recent_activity': """
                        SELECT cache_key, last_hit, hit_count 
                        FROM chat_cache 
                        ORDER BY last_hit DESC 
                        LIMIT 10
                    """,
                    'cache_size': """
                        SELECT pg_size_pretty(pg_total_relation_size('chat_cache')) as size
                    """
                }
                
                stats = {}
                for key, query in queries.items():
                    if key in ['top_cached', 'recent_activity']:
                        rows = await conn.fetch(query)
                        stats[key] = [dict(row) for row in rows]
                    elif key == 'cache_size':
                        row = await conn.fetchrow(query)
                        stats[key] = row['size'] if row else '0 bytes'
                    else:
                        row = await conn.fetchrow(query)
                        stats[key] = row['count'] if row else 0
                
                return stats
                
        except Exception as e:
            logger.error(f"Error getting cache stats: {str(e)}")
            return {}
    
    async def get_cache_performance_stats(self) -> Dict[str, Any]:
        """Get detailed cache performance statistics"""
        stats = await self.get_cache_stats()
        
        total_entries = stats.get('total_entries', 0)
        total_hits = stats.get('total_hits', 0)
        
        if total_entries > 0:
            hit_rate = total_hits / total_entries
            avg_hits = stats.get('avg_hits', 0)
        else:
            hit_rate = 0
            avg_hits = 0
        
        return {
            'total_entries': total_entries,
            'active_entries': stats.get('active_entries', 0),
            'expired_entries': stats.get('expired_entries', 0),
            'total_hits': total_hits,
            'average_hits_per_entry': round(avg_hits, 2),
            'hit_rate': round(hit_rate, 2),
            'cache_efficiency': 'High' if hit_rate > 0.5 else 'Medium' if hit_rate > 0.2 else 'Low',
            'cache_size': stats.get('cache_size', '0 bytes'),
            'top_cached_entries': stats.get('top_cached', []),
            'recent_activity': stats.get('recent_activity', [])
        }
    
    async def search_cache(self, search_term: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search cache entries using PostgreSQL full-text search"""
        try:
            async with self.pool.acquire() as conn:
                query = """
                SELECT cache_key, cache_value, hit_count, created_at, last_hit
                FROM chat_cache 
                WHERE cache_value ILIKE $1 
                   OR metadata::text ILIKE $1
                ORDER BY hit_count DESC, last_hit DESC
                LIMIT $2
                """
                rows = await conn.fetch(query, f'%{search_term}%', limit)
                return [dict(row) for row in rows]
                
        except Exception as e:
            logger.error(f"Error searching cache: {str(e)}")
            return []
    
    async def get_cache_analytics(self) -> Dict[str, Any]:
        """Get advanced cache analytics using PostgreSQL features"""
        try:
            async with self.pool.acquire() as conn:
                analytics = {}
                
                # Cache hit rate over time
                hit_rate_query = """
                SELECT 
                    DATE_TRUNC('hour', last_hit) as hour,
                    COUNT(*) as requests,
                    AVG(hit_count) as avg_hits
                FROM chat_cache 
                WHERE last_hit > (NOW() - INTERVAL '24 hours')
                GROUP BY DATE_TRUNC('hour', last_hit)
                ORDER BY hour DESC
                """
                analytics['hourly_stats'] = [dict(row) for row in await conn.fetch(hit_rate_query)]
                
                # Top cache keys by performance
                top_performance_query = """
                SELECT 
                    cache_key,
                    hit_count,
                    EXTRACT(EPOCH FROM (last_hit - created_at))/3600 as hours_active,
                    hit_count::float / NULLIF(EXTRACT(EPOCH FROM (last_hit - created_at))/3600, 0) as hits_per_hour
                FROM chat_cache 
                WHERE created_at < last_hit
                ORDER BY hits_per_hour DESC
                LIMIT 10
                """
                analytics['top_performance'] = [dict(row) for row in await conn.fetch(top_performance_query)]
                
                # Cache efficiency metrics
                efficiency_query = """
                SELECT 
                    COUNT(*) as total_entries,
                    COUNT(*) FILTER (WHERE hit_count > 0) as entries_with_hits,
                    COUNT(*) FILTER (WHERE hit_count = 0) as unused_entries,
                    AVG(hit_count) as avg_hits,
                    MAX(hit_count) as max_hits
                FROM chat_cache
                """
                row = await conn.fetchrow(efficiency_query)
                analytics['efficiency_metrics'] = dict(row) if row else {}
                
                return analytics
                
        except Exception as e:
            logger.error(f"Error getting cache analytics: {str(e)}")
            return {}
    
    async def get_details(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a cache entry"""
        try:
            async with self.pool.acquire() as conn:
                query = """
                SELECT 
                    cache_key, cache_value, ttl, created_at, accessed_at, 
                    hit_count, last_hit, metadata
                FROM chat_cache 
                WHERE cache_key = $1;
                """
                row = await conn.fetchrow(query, cache_key)
                
                if row:
                    # Calculate age and TTL remaining
                    created_at = row['created_at']
                    current_time = datetime.utcnow()
                    age_seconds = (current_time - created_at).total_seconds()
                    ttl_remaining = max(0, row['ttl'] - age_seconds)
                    
                    return {
                        "cache_key": row['cache_key'],
                        "created_at": created_at.isoformat(),
                        "accessed_at": row['accessed_at'].isoformat() if row['accessed_at'] else None,
                        "last_hit": row['last_hit'].isoformat() if row['last_hit'] else None,
                        "hit_count": row['hit_count'],
                        "ttl": row['ttl'],
                        "ttl_remaining": ttl_remaining,
                        "age_seconds": age_seconds,
                        "metadata": row['metadata'] if row['metadata'] else {}
                    }
                return None
        except Exception as e:
            logger.error(f"Error getting cache details: {str(e)}")
            return None
    
    async def check_cache_status(self) -> Dict[str, Any]:
        """Check if cache is working properly"""
        try:
            async with self.pool.acquire() as conn:
                # Check if table exists
                table_exists_query = """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'chat_cache'
                );
                """
                table_exists = await conn.fetchval(table_exists_query)
                
                if not table_exists:
                    return {
                        "status": "not_created",
                        "message": "Cache table does not exist",
                        "available": False
                    }
                
                # Check table structure
                columns_query = """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'chat_cache' 
                ORDER BY ordinal_position;
                """
                columns = await conn.fetch(columns_query)
                
                # Check if we can perform basic operations
                test_key = "test_cache_status"
                test_value = "test_value"
                
                # Try to insert a test entry
                try:
                    insert_query = """
                    INSERT INTO chat_cache (cache_key, cache_value, ttl) 
                    VALUES ($1, $2, 60)
                    ON CONFLICT (cache_key) DO UPDATE SET
                        cache_value = EXCLUDED.cache_value,
                        accessed_at = NOW()
                    """
                    await conn.execute(insert_query, test_key, test_value)
                    
                    # Try to retrieve it
                    select_query = "SELECT cache_value FROM chat_cache WHERE cache_key = $1"
                    result = await conn.fetchval(select_query, test_key)
                    
                    if result == test_value:
                        # Clean up test entry
                        await conn.execute("DELETE FROM chat_cache WHERE cache_key = $1", test_key)
                        
                        return {
                            "status": "working",
                            "message": "Cache is working properly",
                            "available": True,
                            "columns": [dict(col) for col in columns]
                        }
                    else:
                        return {
                            "status": "error",
                            "message": "Cache read/write test failed",
                            "available": False
                        }
                        
                except Exception as e:
                    return {
                        "status": "error",
                        "message": f"Cache operation failed: {str(e)}",
                        "available": False
                    }
                    
        except Exception as e:
            logger.error(f"Error checking cache status: {str(e)}")
            return {
                "status": "error",
                "message": f"Cache status check failed: {str(e)}",
                "available": False
            } 