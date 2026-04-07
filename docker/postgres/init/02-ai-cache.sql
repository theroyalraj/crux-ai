CREATE TABLE IF NOT EXISTS ai_generation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    prompt_hash TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    system_fingerprint TEXT,
    response_text TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL,
    source TEXT,
    embedding vector(1536),
    input_tokens INT,
    output_tokens INT,
    latency_ms INT,
    cached BOOLEAN NOT NULL DEFAULT false,
    cache_hit_type TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_gen_log_created ON ai_generation_log USING brin (created_at);
CREATE INDEX IF NOT EXISTS idx_gen_log_embedding ON ai_generation_log USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_gen_log_prompt_hash ON ai_generation_log (prompt_hash);
CREATE INDEX IF NOT EXISTS idx_gen_log_metadata ON ai_generation_log USING gin (metadata);
