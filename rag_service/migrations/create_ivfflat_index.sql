-- Migration: Create IVFFlat index on documents_pg table
-- Purpose: Match n8n's PGVector node configuration for fair benchmark comparison
-- 
-- n8n's PGVector Store node uses IVFFlat index by default (not HNSW).
-- This migration creates an IVFFlat index to ensure fair performance comparison.
-- 
-- IVFFlat Index Configuration:
-- - Index Type: IVFFlat (Inverted File with Flat quantization)
-- - Similarity Metric: Cosine similarity (vector_cosine_ops)
-- - Lists: 100 (appropriate for ~10,000 vectors, calculated as sqrt(n))
-- - Probes: 10 (query-time setting for recall vs speed trade-off)
--
-- Lists Calculation:
-- lists = sqrt(n) where n = number of vectors
-- For a dataset of ~10,000 vectors: sqrt(10000) = 100
-- Adjust lists value based on actual dataset size:
--   - 1,000 vectors: lists = 32
--   - 10,000 vectors: lists = 100
--   - 100,000 vectors: lists = 316
--   - 1,000,000 vectors: lists = 1000

-- Drop existing index if it exists (to allow re-running migration)
DROP INDEX IF EXISTS idx_documents_pg_ivfflat_embedding;

-- Create IVFFlat index on the embedding column
-- Using vector_cosine_ops for cosine similarity matching
-- Lists = 100 optimized for ~10,000 vectors
CREATE INDEX idx_documents_pg_ivfflat_embedding 
ON documents_pg 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Set probes for query-time recall/speed trade-off
-- Higher probes = better recall but slower queries
-- Lower probes = faster queries but lower recall
-- Default is 1, we set to 10 for better recall in RAG use case
SET ivfflat.probes = 10;

-- Alternative: Set at database level (requires ALTER DATABASE)
-- ALTER DATABASE your_database_name SET ivfflat.probes = 10;

-- Verify index creation
SELECT 
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes 
WHERE indexname = 'idx_documents_pg_ivfflat_embedding';

-- Show index statistics
SELECT 
    indexrelname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes 
WHERE indexrelname = 'idx_documents_pg_ivfflat_embedding';
