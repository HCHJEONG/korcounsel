ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK(kind IN (
 'VERIFY_ARTIFACT','REBUILD_PROJECTION','FETCH_LAW_DETAIL','FETCH_SCOURT_DETAIL',
 'FETCH_SCOURT_INVENTORY','IMPORT_LEGACY_BUNDLE','ACQUIRE_IMAGE_BATCH',
 'STAGE_LEGACY_READER_BATCH','REFRESH_CURRENT_READER_IMAGES','ENRICH_CURRENT_LAWGO',
 'BUILD_LEGACY_SEARCH','RETRY_CURRENT_IMAGES'
));
CREATE TABLE legacy_search_snapshots (
 snapshot_key text PRIMARY KEY,
 source_sha256 text,
 next_group integer NOT NULL DEFAULT 0,
 row_count bigint NOT NULL DEFAULT 0,
 ready boolean NOT NULL DEFAULT false,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE TABLE legacy_search_rows (
 snapshot_key text NOT NULL REFERENCES legacy_search_snapshots(snapshot_key),
 ordinal bigint NOT NULL,
 search_text text NOT NULL,
 fields jsonb NOT NULL,
 result jsonb NOT NULL,
 PRIMARY KEY(snapshot_key, ordinal)
);
CREATE INDEX legacy_search_trigrams ON legacy_search_rows USING gin(search_text public.gin_trgm_ops);
