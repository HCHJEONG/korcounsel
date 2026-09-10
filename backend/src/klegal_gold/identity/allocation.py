"""Stable internal allocation from an explicit import/request identity, never a source ID."""

from hashlib import sha256


def canonical_id_for_request(request_key: str) -> str:
    """A request identifies registration, not legal equivalence; registry resolves duplicates."""
    if not request_key or request_key != request_key.strip():
        raise ValueError("INVALID_IDENTITY_REQUEST_KEY")
    return "kc:" + sha256(("canonical-allocation-1\0" + request_key).encode()).hexdigest()
