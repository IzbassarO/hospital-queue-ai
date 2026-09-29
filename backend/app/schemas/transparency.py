"""Transparency ledger responses (docs/api.md §6, docs/transparency-ledger.md). Public data only: entries carry
identifiers, hashes and salted commitments; no salt and no free text is ever part of a response here."""

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

ReasonCode = Literal[
    "EMPTY_LEDGER",
    "MALFORMED_ENTRY",
    "NONCANONICAL_VALUE",
    "NONCANONICAL_ENCODING",
    "GENESIS_INVALID",
    "DUPLICATE_SEQ",
    "SEQUENCE_GAP",
    "SEQUENCE_ORDER",
    "PREV_HASH_MISMATCH",
    "ENTRY_HASH_MISMATCH",
    "TRUSTED_HEAD_MISSING",
    "TRUSTED_HEAD_MISMATCH",
    "UNKNOWN_EVENT_TYPE",
    "SOURCE_ROW_MISSING",
    "SALT_MISSING",
    "COMMITMENT_MISMATCH",
    "SOURCE_FIELD_MISMATCH",
    "PUBLICATION_MISMATCH",
    "DUPLICATE_SUBJECT_EVENT",
    "UNCOVERED_SOURCE_ROW",
    "ACTIVE_STATE_MISMATCH",
]


class LedgerReceipt(BaseModel):
    """Proof that an event was chained: the entry's number and hash, enough to find and check it later."""

    ledger_seq: int = Field(description="position of the entry in the ledger (1 = genesis)")
    entry_hash: str = Field(description="SHA-256 of the entry, lowercase hex")
    event_type: str
    subject: str = Field(description="what the entry is about, e.g. specialist_decision:1427")
    created_at: str = Field(description="event time, canonical UTC form YYYY-MM-DDTHH:MM:SS.ffffffZ")
    verify_path: str = Field(description="UI path that opens this entry on the verification page")


class LedgerEntry(BaseModel):
    """One public ledger entry, exactly as hashed and exported."""

    seq: int
    created_at: str = Field(description="canonical UTC timestamp YYYY-MM-DDTHH:MM:SS.ffffffZ")
    event_type: str = Field(
        description="ledger.genesis | publication.published | publication.activated | "
        "publication.deactivated | decision.recorded"
    )
    subject: str
    payload: dict[str, Any] = Field(description="public statement: identifiers, codes, hashes, salted commitments")
    prev_hash: str
    entry_hash: str


class LedgerHead(BaseModel):
    seq: int = Field(description="seq of the newest entry = chain length")
    entry_hash: str
    created_at: str
    chain_length: int
    genesis_hash: str
    protocol: str
    protocol_version: int
    canonicalization: str


class VerificationIssue(BaseModel):
    seq: int | None = Field(description="entry the problem was found at; null for a source row with no entry")
    reason_code: ReasonCode
    subject: str | None
    detail: str = Field(description="what differs, by field name; never a protected value")


class LedgerVerification(BaseModel):
    """Server verification: the public chain plus every covered source row against its entry."""

    status: Literal["OK", "BROKEN"]
    mode: Literal["server"] = "server"
    verified_at: dt.datetime
    duration_ms: int
    chain_length: int = Field(description="entries read")
    verified_through_seq: int = Field(description="every entry up to this seq passed every check")
    head_seq: int | None
    head_hash: str | None
    failure_seq: int | None = None
    reason_code: ReasonCode | None = None
    subject: str | None = None
    issues: list[VerificationIssue] = Field(description="up to 20 problems, first by seq")
    covered_decisions: int = Field(description="decision rows compared with their entries")
    covered_publications: int = Field(description="publication snapshots compared with their entries")
    checks: list[str] = Field(description="what this verification covers")
