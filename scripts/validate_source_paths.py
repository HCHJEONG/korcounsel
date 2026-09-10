"""Explicit bounded live audit against a supplied legacy archive; never imports corpus."""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

from klegal_gold.config import load_settings
from klegal_gold.documents.observe import observe_html
from klegal_gold.domain.identity import SourceSystem
from klegal_gold.ingestion.inventory import collect_inventory
from klegal_gold.sources.law_api import LawOpenApiCaseSource, SourceError
from klegal_gold.sources.scourt import ScourtPortalSource, listing_params
from klegal_gold.storage.files import FileStore


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("--legacy-root", type=Path, required=True)
    args = cli.parse_args()
    root = Path(__file__).resolve().parents[1]
    store = FileStore(root / "data/source-audit")
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "responses": [],
        "listings": [],
        "cases": [],
    }

    def preserve(r):
        b = store.put(r.body)
        report["responses"].append(
            {
                "sha256": b.sha256,
                "size": b.size_bytes,
                "path": b.storage_key,
                "url": r.safe_url,
                "retrieved_at": r.retrieved_at.isoformat(),
                "status": r.status,
            }
        )

    law = LawOpenApiCaseSource(
        load_settings().law_api_credential, preserve=preserve, max_attempts=1
    )
    scourt = ScourtPortalSource(preserve=preserve)
    for source, system, query, limit, display, scope in [
        (
            law,
            SourceSystem.LAW_GO_KR,
            "2017도953",
            2,
            1,
            {"target": "prec", "type": "JSON", "nb": "2017도953"},
        ),
        (scourt, SourceSystem.SCOURT, "2017도953", 3, 1, listing_params("2017도953", 1, 1)),
        (scourt, SourceSystem.SCOURT, "", 3, 5, listing_params("", 1, 5)),
    ]:
        captured = collect_inventory(
            source, system=system, scope=scope, max_pages=limit, display=display, query=query
        )
        report["listings"].append(
            {"snapshot": captured.snapshot.model_dump(mode="json"), "pages": captured.pages}
        )
        print(
            json.dumps(
                {
                    "listing": system,
                    "count": captured.snapshot.observed_unique_count,
                    "state": captured.snapshot.completeness,
                    "failures": captured.snapshot.failed_pages,
                }
            ),
            flush=True,
        )
    # Probe beyond the known single lawgo result, in both formats.
    for fmt in ("JSON", "XML"):
        client = LawOpenApiCaseSource(
            load_settings().law_api_credential, preserve=preserve, format=fmt, max_attempts=1
        )
        for page in (1, 2):
            try:
                result = client.list_page(page=page, display=1, docket="2017도953")
                report.setdefault("law_page_checks", []).append(
                    {"format": fmt, "page": page, "ids": result.ids, "status": "SUCCESS"}
                )
            except SourceError as exc:
                report.setdefault("law_page_checks", []).append(
                    {"format": fmt, "page": page, "status": str(exc)}
                )

    selected = json.loads((root / "data/source-smoke/expanded-selection.json").read_text())
    selected.append(
        {
            "gmeta_contId": "2029039",
            "lmeta_serialno": None,
            "position": None,
            "case_full_no": "legacy non-court/full-text/image specimen",
        }
    )
    legacy_paths = list(args.legacy_root.rglob("*.txt"))
    # Add one observed merged-number row with an available legacy HTML if present.
    names = {p.name for p in legacy_paths}
    for line in (root / "data/legacy-audit/metadata-20241126.jsonl").open():
        row = json.loads(line)
        sid = row.get("gmeta_contId")
        if "," in str(row.get("case_full_no")) and sid and str(sid) + ".txt" in names:
            if not any(x.get("gmeta_contId") == sid for x in selected):
                selected.append(row)
                break
    for row in selected[:12]:
        sid = str(row["gmeta_contId"])
        lid = row.get("lmeta_serialno")
        observation = {
            "scourt_id": sid,
            "law_id": lid,
            "legacy_position": row.get("position"),
            "legacy_case_full_no": row.get("case_full_no"),
            "legacy": [],
        }
        for path in legacy_paths:
            if path.name == sid + ".txt" or re.fullmatch(
                r"[0-9]+-" + re.escape(sid) + r"-[0-9]+\.txt", path.name
            ):
                raw = path.read_bytes()
                b = store.put(raw)
                text = raw.decode("utf-8", errors="strict")
                observation["legacy"].append(
                    {
                        "path": str(path.relative_to(args.legacy_root)),
                        "sha256": b.sha256,
                        "storage_path": b.storage_key,
                        "observation": observe_html(text, "https://glaw.scourt.go.kr/"),
                    }
                )
        started = time.monotonic()
        try:
            detail = scourt.fetch_detail(sid)
            observation["scourt"] = {
                "status": "SUCCESS",
                "sha256": detail.response.sha256,
                "metadata": {
                    k: detail.fields.get(k)
                    for k in (
                        "jisCntntsSrno",
                        "cortNm",
                        "csNoLstCtt",
                        "mrgCsNoCtt",
                        "prnjdgYmd",
                        "adjdTypNm",
                    )
                },
                "observation": observe_html(
                    detail.fields["body"]["orgdocXmlCtt"], "https://portal.scourt.go.kr/"
                ),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        except SourceError as exc:
            observation["scourt"] = {"status": "FAILED", "reason": str(exc)}
        if lid:
            try:
                detail = law.fetch_detail(str(lid))
                observation["law"] = {
                    "status": "SUCCESS",
                    "sha256": detail.response.sha256,
                    "metadata": {
                        k: detail.fields.get(k)
                        for k in ("법원명", "사건번호", "선고일자", "판결유형")
                    },
                    "observation": observe_html(
                        detail.fields.get("판례내용") or "", "https://www.law.go.kr/"
                    ),
                    "editorial_lengths": {
                        k: len(detail.fields.get(k) or "") for k in ("판시사항", "판결요지")
                    },
                }
            except SourceError as exc:
                observation["law"] = {"status": "FAILED", "reason": str(exc)}
        report["cases"].append(observation)
        print(
            json.dumps(
                {
                    "scourt": sid,
                    "status": observation["scourt"]["status"],
                    "legacy_files": len(observation["legacy"]),
                }
            ),
            flush=True,
        )
        (root / "data/source-audit/progress.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2)
        )
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["scope"] = (
        "At most 12 selected legacy cases, bounded listings; "
        "no binary acquisition, OCR, corpus import or identity mutation"
    )
    (root / "docs/step3a-validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print("Audit report saved", flush=True)


if __name__ == "__main__":
    main()
