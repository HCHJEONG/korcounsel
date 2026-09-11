from klegal_gold.ingestion.document_images import image_manifest_from_observation


def test_document_observation_retains_unresolved_and_selects_only_safe_urls() -> None:
    safe = "https://portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?pgmId=PGP1011M04&jisCntntsSrno=77&atchImgFileNm=a.gif"
    manifest = image_manifest_from_observation(
        {"html_sha256": "a" * 64, "images": [{"resolved_url": safe}, {"resolved_url": "https://x.test/a"}]},
        source_id="77",
        parent_artifact_id="manifest:source",
    )
    refs = manifest["image_references"]
    assert isinstance(refs, list)
    assert [ref["reference_status"] for ref in refs] == ["RESOLVED", "UNRESOLVED"]
