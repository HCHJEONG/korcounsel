"""Convert one observed scourt document into an immutable image-reference manifest."""

from __future__ import annotations

from typing import Any

from klegal_gold.assets.images import valid_image_url
from klegal_gold.domain.common import content_hash


def image_manifest_from_observation(
    observation: dict[str, Any], *, source_id: str, parent_artifact_id: str
) -> dict[str, object]:
    images = observation.get("images")
    if not isinstance(images, list):
        raise ValueError("INVALID_DOCUMENT_OBSERVATION")
    references: list[dict[str, object]] = []
    for order, image in enumerate(images):
        if not isinstance(image, dict):
            raise ValueError("INVALID_DOCUMENT_OBSERVATION")
        resolved = image.get("resolved_url")
        url = resolved if isinstance(resolved, str) and valid_image_url(resolved) else None
        name = image.get("name")
        references.append(
            {
                "source_system": "scourt",
                "source_id": source_id,
                "occurrence_order": order,
                "original_src": image.get("original_src"),
                "image_name": name if isinstance(name, str) else None,
                "resolved_url": url,
                "reference_status": "RESOLVED" if url is not None else "UNRESOLVED",
                "reason": (
                    "observed official image endpoint"
                    if url is not None
                    else "no safe observed official image endpoint"
                ),
                "parent_artifact_id": parent_artifact_id,
                "parent_html_sha256": observation.get("html_sha256"),
                "html_line_column": image.get("html_line_column"),
                "provider_mapping_values": image.get("provider_mapping_values", []),
            }
        )
    return {
        "version": "document-image-manifest-1",
        "source_system": "scourt",
        "source_id": source_id,
        "parent_artifact_id": parent_artifact_id,
        "observation_html_sha256": observation.get("html_sha256"),
        "image_references": references,
        "manifest_input_hash": content_hash(str(references).encode()),
    }
