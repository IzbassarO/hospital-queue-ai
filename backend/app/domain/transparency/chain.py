"""The hash chain of the transparency ledger, protocol `aqyl-kezek-transparency-ledger` v1.

Each entry commits to its predecessor::

    entry_hash = SHA-256(canonical_json({"created_at", "event_type", "payload", "prev_hash", "seq", "subject"}))

Entry 1 is the genesis: fixed subject, fixed payload naming the protocol, ``prev_hash`` of 64 zeros and a fixed
timestamp (:data:`GENESIS_CREATED_AT`, the date the v1 protocol was defined). Nothing in the genesis depends on
when or where the migration ran, so every database starts with the same genesis hash and a downgrade followed by
an upgrade reproduces it.

:class:`ChainVerifier` checks a sequence of public entries without any private data (the offline check). What it
proves and what it cannot prove is spelled out in docs/transparency-ledger.md §8.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.domain.transparency.canonical import CanonicalError, canonical_bytes, parse_timestamp

PROTOCOL = "aqyl-kezek-transparency-ledger"
PROTOCOL_VERSION = 1
CANONICALIZATION = "hqai-canonical-json-v1"
COMMITMENT_SCHEME = "sha256-salted-v1"
ZERO_HASH = "0" * 64
GENESIS_CREATED_AT = "2026-09-28T00:00:00.000000Z"
GENESIS_EVENT = "ledger.genesis"
GENESIS_SUBJECT = "ledger:aqyl-kezek"
GENESIS_PAYLOAD: dict[str, Any] = {
    "canonicalization": CANONICALIZATION,
    "commitment_scheme": COMMITMENT_SCHEME,
    "hash_algorithm": "sha256",
    "protocol": PROTOCOL,
    "protocol_version": PROTOCOL_VERSION,
}
ENTRY_FIELDS = ("created_at", "entry_hash", "event_type", "payload", "prev_hash", "seq", "subject")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
EVENT_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+\Z")
SUBJECT_MAX = 256

# Reason codes shared by the server verifier, tools/ledger_verify.py and the browser (docs/transparency-ledger.md §7)
EMPTY_LEDGER = "EMPTY_LEDGER"
MALFORMED_ENTRY = "MALFORMED_ENTRY"
NONCANONICAL_VALUE = "NONCANONICAL_VALUE"
NONCANONICAL_ENCODING = "NONCANONICAL_ENCODING"
GENESIS_INVALID = "GENESIS_INVALID"
DUPLICATE_SEQ = "DUPLICATE_SEQ"
SEQUENCE_GAP = "SEQUENCE_GAP"
SEQUENCE_ORDER = "SEQUENCE_ORDER"
PREV_HASH_MISMATCH = "PREV_HASH_MISMATCH"
ENTRY_HASH_MISMATCH = "ENTRY_HASH_MISMATCH"
TRUSTED_HEAD_MISSING = "TRUSTED_HEAD_MISSING"
TRUSTED_HEAD_MISMATCH = "TRUSTED_HEAD_MISMATCH"


@dataclass(frozen=True)
class LedgerEntry:
    seq: int
    created_at: str
    event_type: str
    subject: str
    payload: dict[str, Any]
    prev_hash: str
    entry_hash: str

    def public(self) -> dict[str, Any]:
        """The entry as exported: exactly the seven public fields."""
        return {
            "created_at": self.created_at,
            "entry_hash": self.entry_hash,
            "event_type": self.event_type,
            "payload": self.payload,
            "prev_hash": self.prev_hash,
            "seq": self.seq,
            "subject": self.subject,
        }


def hash_material(
    seq: int, created_at: str, event_type: str, subject: str, payload: dict[str, Any], prev_hash: str
) -> dict[str, Any]:
    return {
        "created_at": created_at,
        "event_type": event_type,
        "payload": payload,
        "prev_hash": prev_hash,
        "seq": seq,
        "subject": subject,
    }


def entry_hash(
    seq: int, created_at: str, event_type: str, subject: str, payload: dict[str, Any], prev_hash: str
) -> str:
    material = hash_material(seq, created_at, event_type, subject, payload, prev_hash)
    return hashlib.sha256(canonical_bytes(material)).hexdigest()


def make_entry(
    seq: int, created_at: str, event_type: str, subject: str, payload: dict[str, Any], prev_hash: str
) -> LedgerEntry:
    """A new entry with its hash; validates every field first, so nothing outside the contract is ever hashed."""
    _check_fields(seq, created_at, event_type, subject, payload, prev_hash)
    digest = entry_hash(seq, created_at, event_type, subject, payload, prev_hash)
    return LedgerEntry(seq, created_at, event_type, subject, payload, prev_hash, digest)


def genesis() -> LedgerEntry:
    return make_entry(1, GENESIS_CREATED_AT, GENESIS_EVENT, GENESIS_SUBJECT, dict(GENESIS_PAYLOAD), ZERO_HASH)


def _check_fields(seq: Any, created_at: Any, event_type: Any, subject: Any, payload: Any, prev_hash: Any) -> None:
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise CanonicalError("INVALID_SEQ", f"seq {seq!r} is not a positive integer")
    parse_timestamp(created_at)
    if not isinstance(event_type, str) or not EVENT_PATTERN.match(event_type):
        raise CanonicalError("INVALID_EVENT_TYPE", f"event_type {event_type!r}")
    if not isinstance(subject, str) or not subject or len(subject) > SUBJECT_MAX:
        raise CanonicalError("INVALID_SUBJECT", "subject must be a non-empty string of at most 256 characters")
    if not isinstance(payload, dict):
        raise CanonicalError("INVALID_PAYLOAD", "payload must be an object")
    if not isinstance(prev_hash, str) or not HASH_PATTERN.match(prev_hash):
        raise CanonicalError("INVALID_HASH", "prev_hash must be 64 lowercase hex characters")
    canonical_bytes(payload)


def entry_from_public(value: Any) -> LedgerEntry:
    """A parsed export line (or API item) as an entry; raises CanonicalError on a missing/extra/invalid field."""
    if not isinstance(value, dict) or set(value) != set(ENTRY_FIELDS):
        raise CanonicalError(MALFORMED_ENTRY, f"an entry has exactly the fields {', '.join(ENTRY_FIELDS)}")
    _check_fields(
        value["seq"], value["created_at"], value["event_type"], value["subject"], value["payload"], value["prev_hash"]
    )
    if not isinstance(value["entry_hash"], str) or not HASH_PATTERN.match(value["entry_hash"]):
        raise CanonicalError("INVALID_HASH", "entry_hash must be 64 lowercase hex characters")
    return LedgerEntry(
        value["seq"],
        value["created_at"],
        value["event_type"],
        value["subject"],
        value["payload"],
        value["prev_hash"],
        value["entry_hash"],
    )


# ------------------------------------------------------------------------------------------------ commitments
def commitment(salt: str, subject: str, field: str, value: str | None) -> str:
    """Salted SHA-256 commitment to a private field (docs/transparency-ledger.md §4). ``value`` is committed exactly
    as stored: None and "" give different commitments, and text is not trimmed or normalised."""
    if not isinstance(salt, str) or not HASH_PATTERN.match(salt):
        raise CanonicalError("INVALID_SALT", "a salt is 64 lowercase hex characters (32 random bytes)")
    if value is not None and not isinstance(value, str):
        raise CanonicalError("UNSUPPORTED_TYPE", "committed values are strings or null")
    material = {"field": field, "salt": salt, "scheme": COMMITMENT_SCHEME, "subject": subject, "value": value}
    return hashlib.sha256(canonical_bytes(material)).hexdigest()


# ------------------------------------------------------------------------------------------------ verification
@dataclass(frozen=True)
class Failure:
    seq: int | None
    reason_code: str
    subject: str | None
    detail: str


@dataclass(frozen=True)
class ChainResult:
    ok: bool
    chain_length: int
    verified_through_seq: int
    head_hash: str | None
    failure: Failure | None


class ChainVerifier:
    """Incremental check of public entries in seq order: genesis, contiguous seq, prev_hash links, entry hashes and
    an optional trusted head (a (seq, entry_hash) pair recorded earlier that the chain must still contain).
    Stops at the first failure."""

    def __init__(self, trusted_head: tuple[int, str] | None = None) -> None:
        self.trusted_head = trusted_head
        self.count = 0
        self.last: LedgerEntry | None = None
        self.failure: Failure | None = None
        self._trusted_seen = False

    def _fail(self, seq: int | None, code: str, subject: str | None, detail: str) -> Failure:
        self.failure = Failure(seq, code, subject, detail)
        return self.failure

    def add(self, entry: LedgerEntry) -> Failure | None:
        if self.failure is not None:
            return self.failure
        expected_seq = 1 if self.last is None else self.last.seq + 1
        if entry.seq != expected_seq:
            if self.last is not None and entry.seq == self.last.seq:
                code = DUPLICATE_SEQ
            elif entry.seq < expected_seq:
                code = SEQUENCE_ORDER
            else:
                code = SEQUENCE_GAP
            return self._fail(entry.seq, code, entry.subject, f"expected seq {expected_seq}, found {entry.seq}")
        try:
            recomputed = entry_hash(
                entry.seq, entry.created_at, entry.event_type, entry.subject, entry.payload, entry.prev_hash
            )
        except CanonicalError as exc:
            return self._fail(entry.seq, NONCANONICAL_VALUE, entry.subject, str(exc))
        if entry.seq == 1:
            reference = genesis()
            if entry != reference:
                return self._fail(1, GENESIS_INVALID, entry.subject, "entry 1 is not the protocol v1 genesis")
        else:
            assert self.last is not None
            if entry.prev_hash != self.last.entry_hash:
                return self._fail(
                    entry.seq, PREV_HASH_MISMATCH, entry.subject, f"prev_hash does not match entry {self.last.seq}"
                )
        if recomputed != entry.entry_hash:
            return self._fail(
                entry.seq, ENTRY_HASH_MISMATCH, entry.subject, "stored entry_hash differs from the recomputed hash"
            )
        if self.trusted_head is not None and entry.seq == self.trusted_head[0]:
            if entry.entry_hash != self.trusted_head[1]:
                return self._fail(
                    entry.seq, TRUSTED_HEAD_MISMATCH, entry.subject, "entry differs from the trusted head"
                )
            self._trusted_seen = True
        self.count += 1
        self.last = entry
        return None

    def finish(self) -> ChainResult:
        if self.failure is None and self.last is None:
            self._fail(None, EMPTY_LEDGER, None, "no entries")
        if self.failure is None and self.trusted_head is not None and not self._trusted_seen:
            self._fail(self.trusted_head[0], TRUSTED_HEAD_MISSING, None, "the chain is shorter than the trusted head")
        verified = self.last.seq if self.last else 0
        if self.failure is not None and self.failure.seq is not None:
            verified = min(verified, self.failure.seq - 1)
        return ChainResult(
            ok=self.failure is None,
            chain_length=self.count,
            verified_through_seq=verified,
            head_hash=self.last.entry_hash if self.last else None,
            failure=self.failure,
        )


def verify_chain(entries: Iterable[LedgerEntry], trusted_head: tuple[int, str] | None = None) -> ChainResult:
    verifier = ChainVerifier(trusted_head)
    for entry in entries:
        if verifier.add(entry) is not None:
            break
    return verifier.finish()
