"""Conservative, versioned decision-kind and docket observations; no fuzzy matching."""

import re

from klegal_gold.domain.identity import (
    CaseMetadata,
    CourtCaseKey,
    DecisionKey,
    DecisionKind,
)

VERSION = "decision-key-1"
KINDS = {
    "판결": DecisionKind.JUDGMENT,
    "전원합의체판결": DecisionKind.JUDGMENT,
    "결정": DecisionKind.DECISION,
    "전원합의체결정": DecisionKind.DECISION,
    "중간판결": DecisionKind.INTERLOCUTORY,
    "명령": DecisionKind.ORDER,
    "재결": DecisionKind.ADJUDICATION,
}
DOCKET = re.compile(r"([0-9]{2,4}[가-힣]+)([0-9]+)")


def decision_kind(raw: str | None) -> DecisionKind | None:
    """Recognize only observed spellings; retain unknown raw values in source metadata."""
    return KINDS.get(raw.strip()) if raw else None


def docket_aliases(raw: str) -> tuple[str, ...]:
    """Accept full dockets and explicit comma-separated numeric continuations only."""
    result: list[str] = []
    prefix: str | None = None
    for part in raw.split(","):
        part = part.strip()
        match = DOCKET.fullmatch(part)
        if match:
            prefix = match[1]
            alias = part
        elif prefix and re.fullmatch(r"[0-9]+", part):
            alias = prefix + part
        else:
            return ()
        if alias in result:
            return ()
        result.append(alias)
    return tuple(result)


def decision_keys(
    metadata: CaseMetadata, case_keys: tuple[CourtCaseKey, ...]
) -> tuple[DecisionKey, ...]:
    """Derive keys without adding fields to immutable historical identity payloads."""
    kind = decision_kind(metadata.disposition)
    if kind is None:
        return ()
    result: set[DecisionKey] = set()
    for key in case_keys:
        if metadata.court is not None and metadata.court != key.court:
            raise ValueError("CONFLICTING_DECISION_COURT")
        aliases = docket_aliases(key.case_number)
        if not aliases or key.court != key.court.strip():
            return ()
        result.update(
            DecisionKey(court=key.court, case_number=alias, decision_kind=kind) for alias in aliases
        )
    if metadata.case_numbers:
        metadata_aliases: set[str] = set()
        for raw in metadata.case_numbers:
            aliases = docket_aliases(raw)
            if not aliases:
                return ()
            metadata_aliases.update(aliases)
        if metadata_aliases != {key.case_number for key in result}:
            raise ValueError("CONFLICTING_DECISION_DOCKETS")
    return tuple(sorted(result, key=lambda key: (key.court, key.case_number, key.decision_kind)))
