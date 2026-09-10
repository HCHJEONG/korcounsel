"""Connect acquired responses to immutable files, receipts and source versions."""

import json
from uuid import uuid4

from klegal_gold.db.records import Records
from klegal_gold.domain.artifacts import ArtifactType, SourceArtifact
from klegal_gold.domain.cases import RawLegalCase
from klegal_gold.domain.identity import SourceCaseIdentifier, SourceCaseVersion, SourceSystem
from klegal_gold.domain.provenance import Provenance
from klegal_gold.sources.law_api import VERSION, Detail, Response


def preserve_response(
    records: Records, response: Response, run_id: str, source: SourceSystem = SourceSystem.LAW_GO_KR
) -> str:
    # A per-acquisition receipt separates changing timestamps from stable byte identity.
    artifact_id = "http:" + response.sha256
    records.put_artifact(
        artifact_id,
        response.body,
        origin="HTTP_RESPONSE",
        metadata={"kind": "SOURCE_HTTP_RESPONSE"},
    )
    records.put_artifact(
        "http-receipt:" + str(uuid4()),
        json.dumps(
            {
                "run_id": run_id,
                "source": source,
                "url": response.safe_url,
                "retrieved_at": response.retrieved_at.isoformat(),
                "status": response.status,
                "mime_type": response.mime_type,
                "attempt": response.attempts,
                "collector_version": VERSION
                if source == SourceSystem.LAW_GO_KR
                else "scourt-portal-2",
            },
            sort_keys=True,
        ).encode(),
        origin="DERIVED",
        metadata={"kind": "HTTP_ATTEMPT"},
        parent_id=artifact_id,
    )
    return artifact_id


def save_detail(
    records: Records, detail: Detail, run_id: str, source: SourceSystem = SourceSystem.LAW_GO_KR
) -> str:
    response = detail.response
    digest = response.sha256
    version = SourceCaseVersion(
        identifier=SourceCaseIdentifier(
            source=source,
            source_id=detail.source_id,
        ),
        raw_content_hash=digest,
    )
    artifact_id = f"{source}:{detail.source_id}:{digest}"
    artifact = SourceArtifact(
        artifact_id=artifact_id,
        source_version=version,
        artifact_type=ArtifactType.JSON
        if response.body.decode("utf-8-sig").lstrip().startswith("{")
        else ArtifactType.XML,
        representation="RESPONSE_BYTES",
        source_url=response.safe_url,
        retrieved_at=response.retrieved_at,
        mime_type=response.mime_type,
        sha256=digest,
        file_size=len(response.body),
        storage_path=f"blobs/{digest[:2]}/{digest}",
    )
    model = RawLegalCase(
        source_version=version,
        raw_artifact=artifact,
        provenance=Provenance(
            source_version=version,
            raw_artifact_id=artifact_id,
            source_url=response.safe_url,
            retrieved_at=response.retrieved_at,
            decoder_version="utf8-strict-1",
            text_extractor_version=VERSION
            if source == SourceSystem.LAW_GO_KR
            else "scourt-portal-2",
            parser_version="NOT_APPLIED",
            normalizer_version="NOT_APPLIED",
            dataset_version="UNRELEASED",
            run_id=run_id,
        ),
    )
    records.save_raw(model, response.body, receipt_id=uuid4())
    return artifact_id
