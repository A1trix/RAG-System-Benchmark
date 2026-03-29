# pgvector IVFFlat Index Migration

## Overview

This migration creates an IVFFlat index on the `documents_pg` table to match n8n's PGVector node configuration for fair benchmark comparison.

## Why IVFFlat?

n8n's PGVector Store node uses IVFFlat index by default (not HNSW). To ensure fair performance comparison, we use the same index type.

### Index Characteristics

| Feature | IVFFlat | HNSW |
|---------|---------|------|
| Build Time | Fast | Slow |
| Memory Usage | Lower | Higher |
| Query Speed | Fast | Very Fast |
| Recall Accuracy | Good | Excellent |
| Best For | Medium datasets | Large datasets |

## Configuration

### Lists Parameter

The `lists` parameter determines the number of inverted lists (clusters) in the index:

- **Formula**: `lists = sqrt(n)` where n = number of vectors
- **Recommended values**:
  - 1,000 vectors: `lists = 32`
  - 10,000 vectors: `lists = 100` (current setting)
  - 100,000 vectors: `lists = 316`
  - 1,000,000 vectors: `lists = 1000`

### Probes Parameter

The `probes` parameter controls how many lists are searched at query time:

- **Default**: 1
- **Current**: 10 (for better recall)
- **Trade-off**: Higher probes = better recall but slower queries

## Usage

### Apply Migration

```bash
# Connect to your PostgreSQL database and run the migration
psql -d your_database -f migrations/create_ivfflat_index.sql
```

### Verify Index

```sql
-- Check if index exists
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE indexname = 'idx_documents_pg_ivfflat_embedding';

-- Check index usage statistics
SELECT schemaname, tablename, indexname, idx_scan 
FROM pg_stat_user_indexes 
WHERE indexrelname = 'idx_documents_pg_ivfflat_embedding';
```

### Adjust Lists for Your Dataset

If your dataset size differs from the assumed ~10,000 vectors:

```sql
-- Recalculate lists based on actual count
SELECT sqrt(count(*))::int as recommended_lists 
FROM documents_pg;

-- Rebuild index with new lists value (replace 100 with your value)
DROP INDEX idx_documents_pg_ivfflat_embedding;
CREATE INDEX idx_documents_pg_ivfflat_embedding 
ON documents_pg 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = YOUR_VALUE);
```

## Performance Tuning

### Query-Time Probes

Set probes per session or connection:

```sql
-- Per session (current migration approach)
SET ivfflat.probes = 10;

-- Per connection string (application-level)
-- Add to connection parameters: options='-c ivfflat.probes=10'
```

### Monitoring

Monitor index effectiveness:

```sql
-- Check if index is being used
EXPLAIN ANALYZE
SELECT text, metadata, 1 - (embedding <=> '[your_query_embedding]'::vector) AS score
FROM documents_pg
ORDER BY embedding <=> '[your_query_embedding]'::vector
LIMIT 10;

-- Should show "Index Scan using idx_documents_pg_ivfflat_embedding"
```

## n8n Alignment

This configuration matches n8n's default PGVector Store node behavior:
- Same index type (IVFFlat)
- Same similarity metric (cosine)
- Comparable performance characteristics

## References

- [pgvector IVFFlat Documentation](https://github.com/pgvector/pgvector#ivfflat)
- [n8n PGVector Store Node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.pgvectorstore/)
