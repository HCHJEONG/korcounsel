CREATE EXTENSION IF NOT EXISTS pg_trgm;
ALTER TABLE case_projection ADD COLUMN search_text text;
CREATE INDEX case_projection_search_text ON case_projection USING gin(search_text gin_trgm_ops);