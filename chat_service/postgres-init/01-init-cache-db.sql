-- PostgreSQL Cache Database Initialization Script
-- This script sets up the chat_cache table and optimizations

-- Create the cache table with PostgreSQL-specific optimizations
CREATE TABLE IF NOT EXISTS chat_cache (
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

-- Create optimized indexes for better performance
CREATE INDEX IF NOT EXISTS idx_cache_key ON chat_cache (cache_key);
CREATE INDEX IF NOT EXISTS idx_created_at_ttl ON chat_cache (created_at, ttl);
CREATE INDEX IF NOT EXISTS idx_hit_count ON chat_cache (hit_count DESC);
CREATE INDEX IF NOT EXISTS idx_last_hit ON chat_cache (last_hit DESC);
CREATE INDEX IF NOT EXISTS idx_metadata ON chat_cache USING GIN (metadata);

-- Insert some initial cache entries for testing
INSERT INTO chat_cache (cache_key, cache_value, ttl, created_at, accessed_at, hit_count, last_hit, metadata) 
VALUES 
('init_key_1', '{"message": "Cache system initialized", "timestamp": "2025-01-07T10:33:00Z"}', 86400, NOW(), NOW(), 0, NOW(), '{"type": "system", "version": "1.0.0"}'::jsonb),
('init_key_2', '{"message": "Welcome to BrainKB Chat Cache", "timestamp": "2025-01-07T10:33:00Z"}', 86400, NOW(), NOW(), 0, NOW(), '{"type": "welcome", "service": "chat"}'::jsonb)
ON CONFLICT (cache_key) DO NOTHING;

-- Create a function for automatic cache cleanup
CREATE OR REPLACE FUNCTION cleanup_expired_cache()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM chat_cache 
    WHERE created_at < (NOW() - INTERVAL '1 second' * ttl);
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    
    -- Log cleanup activity
    INSERT INTO chat_cache (cache_key, cache_value, ttl, metadata) 
    VALUES ('cleanup_log', 
            json_build_object('deleted_count', deleted_count, 'timestamp', NOW())::text,
            3600,
            json_build_object('type', 'cleanup_log', 'deleted_count', deleted_count)::jsonb)
    ON CONFLICT (cache_key) DO UPDATE SET
        cache_value = EXCLUDED.cache_value,
        accessed_at = NOW(),
        metadata = EXCLUDED.metadata;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Create a function to get cache statistics
CREATE OR REPLACE FUNCTION get_cache_stats()
RETURNS JSON AS $$
DECLARE
    stats JSON;
BEGIN
    SELECT json_build_object(
        'total_entries', (SELECT COUNT(*) FROM chat_cache),
        'active_entries', (SELECT COUNT(*) FROM chat_cache WHERE created_at > (NOW() - INTERVAL '1 second' * ttl)),
        'expired_entries', (SELECT COUNT(*) FROM chat_cache WHERE created_at <= (NOW() - INTERVAL '1 second' * ttl)),
        'total_hits', (SELECT COALESCE(SUM(hit_count), 0) FROM chat_cache),
        'avg_hits', (SELECT COALESCE(AVG(hit_count), 0) FROM chat_cache),
        'cache_size', (SELECT pg_size_pretty(pg_total_relation_size('chat_cache'))),
        'last_cleanup', (SELECT cache_value FROM chat_cache WHERE cache_key = 'cleanup_log' ORDER BY created_at DESC LIMIT 1)
    ) INTO stats;
    
    RETURN stats;
END;
$$ LANGUAGE plpgsql;

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON TABLE chat_cache TO postgres;
GRANT USAGE, SELECT ON SEQUENCE chat_cache_id_seq TO postgres;

-- Show the created table structure
\d chat_cache;

-- Show initial cache entries
SELECT cache_key, LEFT(cache_value, 50) as preview, ttl, created_at FROM chat_cache LIMIT 5; 