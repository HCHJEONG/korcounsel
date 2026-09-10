-- Derived index only: historical JSON/events remain byte-for-byte unchanged.
-- Existing complete keys are backfilled conservatively. Conflicts abort the migration.
SELECT pg_advisory_xact_lock(72834002);
CREATE TABLE active_decision_keys (
    court text NOT NULL CHECK (btrim(court) <> '' AND court = btrim(court)),
    case_number text NOT NULL CHECK (case_number ~ '^[0-9]{2,4}[가-힣]+[0-9]+$'),
    decision_kind text NOT NULL CHECK (decision_kind IN ('판결','결정','중간판결','명령','재결')),
    canonical_id text NOT NULL,
    revision integer NOT NULL,
    PRIMARY KEY(court, case_number, decision_kind),
    FOREIGN KEY(canonical_id, revision) REFERENCES document_revisions(canonical_id, revision)
);
-- A migration must not guess abbreviated/merged docket parsing in SQL. Existing active
-- records with recognized kinds and unsupported docket spelling require explicit review.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM documents d
        JOIN document_revisions r ON (r.canonical_id,r.revision)=(d.canonical_id,d.current_revision)
        JOIN document_case_keys dk ON (dk.canonical_id,dk.revision)=(r.canonical_id,r.revision)
        JOIN case_keys k ON k.key_id=dk.key_id
        WHERE d.active AND btrim(r.payload->'metadata'->>'disposition')
          IN ('판결','전원합의체판결','결정','전원합의체결정','중간판결','명령','재결')
          AND (k.case_number !~ '^[0-9]{2,4}[가-힣]+[0-9]+$'
               OR k.court <> btrim(k.court)
               OR (r.payload->'metadata'->>'court' IS NOT NULL
                   AND r.payload->'metadata'->>'court' <> k.court))
    ) THEN
        RAISE EXCEPTION 'DECISION_KEY_BACKFILL_REVIEW_REQUIRED';
    END IF;
END;
$$;
INSERT INTO active_decision_keys
SELECT k.court,k.case_number,
       CASE btrim(r.payload->'metadata'->>'disposition')
         WHEN '전원합의체판결' THEN '판결'
         WHEN '전원합의체결정' THEN '결정'
         ELSE btrim(r.payload->'metadata'->>'disposition') END,
       d.canonical_id,d.current_revision
FROM documents d
JOIN document_revisions r ON (r.canonical_id,r.revision)=(d.canonical_id,d.current_revision)
JOIN document_case_keys dk ON (dk.canonical_id,dk.revision)=(r.canonical_id,r.revision)
JOIN case_keys k ON k.key_id=dk.key_id
WHERE d.active AND btrim(r.payload->'metadata'->>'disposition')
  IN ('판결','전원합의체판결','결정','전원합의체결정','중간판결','명령','재결');
