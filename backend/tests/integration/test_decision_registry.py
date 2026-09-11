"""Actual PostgreSQL constraints, concurrent registration, revisions and upgrade preservation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from klegal_gold.db.migrate import migrate
from klegal_gold.db.registry import Registry
from klegal_gold.domain.identity import (
    CanonicalCaseIdentity,
    CaseMetadata,
    CourtCaseKey,
    DecisionKey,
    IdentityLinkEvent,
    SourceCaseIdentifier,
)

pytestmark = pytest.mark.integration


def arguments(source_id="old", kind="판결", docket="85후40", date=None):
    return dict(
        metadata=CaseMetadata(
            court="대법원", case_numbers=(docket,), disposition=kind, decision_date=date
        ),
        court_case_keys=(CourtCaseKey(court="대법원", case_number=docket),),
        source_identifiers=(SourceCaseIdentifier(source="scourt", source_id=source_id),),
        actor="synthetic-test",
        reason="explicitly verified synthetic registration",
    )


def relink(old, **changes):
    newer = CanonicalCaseIdentity.model_validate(
        old.model_dump() | {"link_revision": old.link_revision + 1} | changes
    )
    return IdentityLinkEvent(
        event_id=uuid4(),
        operation="RELINK",
        previous=(old,),
        resulting=(newer,),
        recorded_at=datetime.now(UTC),
        actor="synthetic-test",
        reason="verified synthetic change",
    )


def test_registration_retry_concurrency_and_conflicting_request(db):
    registry = Registry(db)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: registry.register("row:a", **arguments()), range(2)))
    assert results[0] == results[1]
    assert results[0].canonical_id.startswith("kc:")
    assert len(registry.snapshot()["events"]) == 1
    with pytest.raises(ValueError, match="IDENTITY_REQUEST_CONFLICT"):
        registry.register("row:a", **arguments("changed"))
    assert len(registry.snapshot()["events"]) == 1


def test_same_decision_different_source_or_date_is_not_new_document(db):
    registry = Registry(db)
    original = registry.register("row:a", **arguments())
    for date in (None, "1986-10-28"):
        with pytest.raises(ValueError, match="DECISION_KEY_ALREADY_LINKED"):
            registry.register("row:b", **arguments("different", date=date))
    key = DecisionKey(court="대법원", case_number="85후40", decision_kind="판결")
    assert registry.find_decision(key) == original
    assert len(registry.snapshot()["events"]) == 1


def test_same_case_different_decisions_and_merged_aliases(db):
    registry = Registry(db)
    records = [
        registry.register(kind, **arguments(kind, kind=kind))
        for kind in ("판결", "결정", "중간판결")
    ]
    assert len({record.canonical_id for record in records}) == 3
    combined = registry.register("merged", **arguments("merged", docket="2020다296741, 296758"))
    for docket in ("2020다296741", "2020다296758"):
        assert (
            registry.find_decision(
                DecisionKey(court="대법원", case_number=docket, decision_kind="판결")
            )
            == combined
        )
    with pytest.raises(ValueError, match="DECISION_KEY_ALREADY_LINKED"):
        registry.register("duplicate-alias", **arguments("duplicate", docket="2020다296758"))


def test_old_new_source_aliases_relink_keep_original_and_registration_retry(db):
    registry = Registry(db)
    old = registry.register("row:a", **arguments())
    update = relink(
        old,
        source_identifiers=[
            *old.source_identifiers,
            SourceCaseIdentifier(source="scourt", source_id="new"),
            SourceCaseIdentifier(source="law_go_kr", source_id="law"),
        ],
    )
    registry.apply(update)
    registry.apply(update)
    assert registry.get(old.canonical_id, 1) == old
    assert len(registry.get(old.canonical_id).source_identifiers) == 3
    assert registry.register("row:a", **arguments()) == old
    key = DecisionKey(court="대법원", case_number="85후40", decision_kind="판결")
    assert registry.find_decision(key).link_revision == 2


def test_relink_key_conflict_rolls_back_old_links(db):
    registry = Registry(db)
    first = registry.register("first", **arguments())
    second = registry.register("second", **arguments("second", kind="결정"))
    update = relink(second, metadata=first.metadata)
    with pytest.raises(ValueError, match="DECISION_KEY_ALREADY_LINKED"):
        registry.apply(update)
    assert registry.get(second.canonical_id) == second
    assert len(registry.snapshot()["events"]) == 2


def test_missing_and_unsupported_kind_remain_unregistered(db):
    registry = Registry(db)
    for kind in (None, "민사", "판결/결정"):
        with pytest.raises(ValueError, match="INCOMPLETE_DECISION_KEY"):
            registry.register("missing", **arguments(kind=kind))
    assert registry.snapshot()["events"] == []


def seed_old_identity(db, canonical="scourt:old", kind="판결", docket="85후40"):
    """Write the pre-0007 schema directly to test real upgrades, not the new repository."""
    record = CanonicalCaseIdentity(
        canonical_id=canonical,
        link_revision=1,
        metadata=CaseMetadata(court="대법원", disposition=kind),
        court_case_keys=(CourtCaseKey(court="대법원", case_number=docket),),
        source_identifiers=(SourceCaseIdentifier(source="scourt", source_id=canonical),),
    )
    event = IdentityLinkEvent(
        event_id=uuid4(),
        operation="CREATE",
        resulting=(record,),
        recorded_at=datetime.now(UTC),
        actor="synthetic-old",
        reason="old schema fixture",
    )
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO identity_events(event_id,payload) VALUES(%s,%s)",
            (event.event_id, Jsonb(event.model_dump(mode="json"))),
        )
        conn.execute("INSERT INTO documents VALUES(%s,1,true)", (canonical,))
        conn.execute(
            "INSERT INTO document_revisions VALUES(%s,1,%s,%s)",
            (canonical, event.event_id, Jsonb(record.model_dump(mode="json"))),
        )
        conn.execute(
            "INSERT INTO case_keys(court,case_number) VALUES('대법원',%s) ON CONFLICT DO NOTHING",
            (docket,),
        )
        conn.execute(
            "INSERT INTO document_case_keys SELECT %s,1,key_id FROM case_keys "
            "WHERE court='대법원' AND case_number=%s",
            (canonical, docket),
        )
    return record


def test_upgrade_backfills_without_mutating_history(empty_db):
    migrate(empty_db, target=6)
    old = seed_old_identity(empty_db)
    before = Registry(empty_db).snapshot()
    assert migrate(empty_db) == [
        "0007_decision_keys.sql",
        "0008_legacy_import.sql",
        "0009_case_search_text.sql",
        "0010_image_acquisition.sql",
        "0011_legacy_reader_batches.sql",
    ]
    with empty_db.connect() as conn:
        extension = conn.execute(
            "SELECT n.nspname AS schema FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='pg_trgm'"
        ).fetchone()
        assert extension["schema"] == "public"
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM information_schema.tables "
                "WHERE table_schema=%s AND table_name='schema_migrations'",
                (empty_db.schema,),
            ).fetchone()["n"]
            == 1
        )
    registry = Registry(empty_db)
    assert registry.snapshot() == before
    assert (
        registry.find_decision(
            DecisionKey(court="대법원", case_number="85후40", decision_kind="판결")
        )
        == old
    )
    # Database itself enforces uniqueness independently of Python checks.
    with pytest.raises(psycopg.errors.UniqueViolation):
        with empty_db.connect() as conn:
            conn.execute("INSERT INTO active_decision_keys SELECT * FROM active_decision_keys")


def test_upgrade_conflicting_keys_aborts_without_deleting_history(empty_db):
    migrate(empty_db, target=6)
    seed_old_identity(empty_db)
    seed_old_identity(empty_db, canonical="another")
    before = Registry(empty_db).snapshot()
    with pytest.raises(psycopg.errors.UniqueViolation):
        migrate(empty_db)
    assert Registry(empty_db).snapshot() == before
    with empty_db.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 6
        assert (
            conn.execute("SELECT to_regclass('active_decision_keys') AS t").fetchone()["t"] is None
        )


def test_upgrade_unsupported_merged_spelling_requires_review(empty_db):
    migrate(empty_db, target=6)
    seed_old_identity(empty_db, docket="85후40, 41")
    with pytest.raises(psycopg.Error, match="BACKFILL_REVIEW_REQUIRED"):
        migrate(empty_db)


def test_snapshot_replay_rebuilds_keys_and_registration_identity(db, empty_db):
    from psycopg import sql

    from klegal_gold.db.session import Database

    registry = Registry(db)
    original = registry.register("row:a", **arguments(docket="85후40, 41"))
    registry.apply(
        relink(
            original,
            source_identifiers=[
                *original.source_identifiers,
                SourceCaseIdentifier(source="scourt", source_id="new"),
            ],
        )
    )
    snapshot = registry.snapshot()
    schema = db.schema + "_restore"
    with db.connect() as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        other = Database(db._dsn, schema=schema)
        migrate(other)
        restored = Registry(other)
        restored.restore(snapshot)
        restored.restore(snapshot)
        assert restored.snapshot() == snapshot
        assert restored.register("row:a", **arguments(docket="85후40, 41")) == original
        assert (
            restored.find_decision(
                DecisionKey(court="대법원", case_number="85후41", decision_kind="판결")
            ).link_revision
            == 2
        )
    finally:
        with db.connect() as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_simultaneous_different_requests_for_same_key_have_one_winner(db):
    registry = Registry(db)

    def register_one(key):
        try:
            return registry.register(key, **arguments(source_id=key))
        except ValueError as error:
            assert str(error) == "DECISION_KEY_ALREADY_LINKED"
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(register_one, ("first", "second")))
    assert sum(result is not None for result in results) == 1
    assert len(registry.snapshot()["events"]) == 1


def test_branch_is_not_collapsed(db):
    registry = Registry(db)
    first = registry.register("main", **arguments())
    args = arguments(source_id="branch")
    args["metadata"] = CaseMetadata(court="대법원 지원", disposition="판결")
    args["court_case_keys"] = (CourtCaseKey(court="대법원 지원", case_number="85후40"),)
    second = registry.register("branch", **args)
    assert first.canonical_id != second.canonical_id
