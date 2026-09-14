CREATE TABLE current_reader_search (
 artifact_id text PRIMARY KEY REFERENCES artifacts(artifact_id),
 title_text text NOT NULL,
 html_text text NOT NULL
);
CREATE INDEX current_reader_html_trigrams ON current_reader_search USING gin(html_text public.gin_trgm_ops);
