"""Stage a bounded image acquisition manifest from legacy image target groups."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", type=Path, default=Path("data/repair-audit-20260910/image-target-groups.json"))
    parser.add_argument("--cross-document", type=Path, default=Path("data/repair-audit-20260910/image-inventory-details.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-urls", type=int, default=50)
    return parser.parse_args()


def _filename(url: str) -> str | None:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    value = query.get("attachImgNm", [None])[0]
    return value.strip() if isinstance(value, str) and value.strip() else None


def main() -> None:
    args = _parse_args()
    groups = json.loads(args.groups.read_text(encoding="utf-8"))
    details = json.loads(args.cross_document.read_text(encoding="utf-8"))
    mismatch_pairs = {
        (str(item.get("row_id")), str(item.get("image_id")))
        for item in details.get("cross_document_refs", [])
        if isinstance(item, dict)
    }
    refs: list[dict[str, object]] = []
    seen: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        source_id = str(group.get("source_id", "UNKNOWN"))
        positions = group.get("positions") if isinstance(group.get("positions"), list) else []
        row_position = positions[0] if positions else None
        for order, url in enumerate(group.get("urls", [])):
            if not isinstance(url, str) or url in seen:
                continue
            seen.add(url)
            parsed = urlparse(url)
            cont_id = parse_qs(parsed.query).get("contId", [""])[0]
            is_mismatch = (source_id, str(cont_id)) in mismatch_pairs
            refs.append(
                {
                    "source_system": "scourt",
                    "source_id": source_id,
                    "row_position": row_position,
                    "occurrence_order": order,
                    "original_src": url,
                    "image_name": _filename(url),
                    "legacy_contId": cont_id,
                    "reference_status": "ID_MISMATCH" if is_mismatch else "NAME_ONLY",
                    "reason": (
                        "cross-document image identifier observed"
                        if is_mismatch
                        else "legacy glaw URL preserved; current portal URL requires fresh provider mapping"
                    ),
                    "legacy_group": group,
                }
            )
            if len(refs) >= args.max_urls:
                break
        if len(refs) >= args.max_urls:
            break
    payload = {
        "kind": "IMAGE_REFERENCE_MANIFEST",
        "source": str(args.groups),
        "total_target_urls_observed": details.get("target_urls"),
        "staged_url_count": len(refs),
        "image_references": refs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "staged_url_count": len(refs)}, ensure_ascii=False))


if __name__ == "__main__":
    main()