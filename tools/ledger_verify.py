#!/usr/bin/env python3
"""Offline verifier of an Aqyl Kezek transparency-ledger export. Python standard library only.

    python3 tools/ledger_verify.py ledger.jsonl
    python3 tools/ledger_verify.py ledger.jsonl --trusted-head 1427:83ab…12f9   # a head you recorded earlier
    python3 tools/ledger_verify.py ledger.jsonl --expect-head 83ab…12f9         # the export must end there
    HQAI_API_KEY=… python3 tools/ledger_verify.py --url http://localhost:8000     # fetch GET /transparency/export
    make ledger-verify FILE=ledger.jsonl [HEAD=seq:hash]

It re-implements, independently of the backend, the canonical JSON contract `hqai-canonical-json-v1` and the chain
rules of protocol v1 (docs/transparency-ledger.md), and checks every line: canonical encoding, genesis, contiguous
seq, prev_hash links and entry hashes, plus the optional trusted head. Exit code 0 = VERIFIED, 1 = BROKEN,
2 = the file or URL could not be read.

What this proves: the export is one unbroken chain from the protocol genesis, and — with a trusted head — that it
still contains the entry you recorded earlier. What it cannot prove: that the application's current database rows
still match their commitments (the export has no private salts, by design); that is the server verification
(GET /api/v1/transparency/verify). A full rewrite of the ledger with recomputed hashes is only detected against a
head recorded outside the system (docs/transparency-ledger.md §8).

The API key for --url is read from the HQAI_API_KEY environment variable and sent as the X-API-Key header, never in
the URL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from collections.abc import Iterable, Iterator
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1
MAX_DEPTH = 32
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
EVENT_PATTERN = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+\Z")
ENTRY_FIELDS = ("created_at", "entry_hash", "event_type", "payload", "prev_hash", "seq", "subject")
ZERO_HASH = "0" * 64
GENESIS = {
    "seq": 1,
    "created_at": "2026-09-28T00:00:00.000000Z",
    "event_type": "ledger.genesis",
    "subject": "ledger:aqyl-kezek",
    "payload": {
        "canonicalization": "hqai-canonical-json-v1",
        "commitment_scheme": "sha256-salted-v1",
        "hash_algorithm": "sha256",
        "protocol": "aqyl-kezek-transparency-ledger",
        "protocol_version": 1,
    },
    "prev_hash": ZERO_HASH,
}
SHORT_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


class Broken(Exception):
    def __init__(self, code: str, seq: int | None, detail: str) -> None:
        super().__init__(detail)
        self.code, self.seq, self.detail = code, seq, detail


class NotCanonical(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


# ------------------------------------------------------------------------------------------------ canonical JSON
def _string(value: str) -> str:
    if "\x00" in value:
        raise NotCanonical("NUL_IN_STRING", "U+0000 in a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise NotCanonical("LONE_SURROGATE", "lone surrogate in a string") from exc
    parts = []
    for char in value:
        if char in SHORT_ESCAPES:
            parts.append(SHORT_ESCAPES[char])
        elif char < " ":
            parts.append(f"\\u{ord(char):04x}")
        else:
            parts.append(char)
    return '"' + "".join(parts) + '"'


def canonical(value: Any, depth: int = 0) -> str:
    if depth > MAX_DEPTH:
        raise NotCanonical("TOO_DEEP", "nesting deeper than 32")
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise NotCanonical("INTEGER_OUT_OF_RANGE", str(value))
        return str(value)
    if isinstance(value, float):
        raise NotCanonical("FLOAT_NOT_ALLOWED", repr(value))
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(canonical(item, depth + 1) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str) or not KEY_PATTERN.match(key):
                raise NotCanonical("INVALID_KEY", repr(key))
        return "{" + ",".join(_string(k) + ":" + canonical(value[k], depth + 1) for k in sorted(value)) + "}"
    raise NotCanonical("UNSUPPORTED_TYPE", type(value).__name__)


def _float(text: str) -> Any:
    raise NotCanonical("FLOAT_NOT_ALLOWED", text)


def _constant(text: str) -> Any:
    raise NotCanonical("MALFORMED_JSON", f"{text} is not JSON")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise NotCanonical("DUPLICATE_KEY", repr(key))
        out[key] = value
    return out


def parse_strict(text: str) -> Any:
    try:
        value = json.loads(text, parse_float=_float, parse_constant=_constant, object_pairs_hook=_pairs)
    except NotCanonical:
        raise
    except ValueError as exc:
        raise NotCanonical("MALFORMED_JSON", str(exc)) from exc
    canonical(value)
    return value


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------------------------------------ chain
def entry_hash(entry: dict[str, Any]) -> str:
    material = {key: entry[key] for key in ("created_at", "event_type", "payload", "prev_hash", "seq", "subject")}
    return sha256_hex(canonical(material))


def _check_entry(entry: Any, line_seq: int | None) -> dict[str, Any]:
    if not isinstance(entry, dict) or set(entry) != set(ENTRY_FIELDS):
        raise Broken("MALFORMED_ENTRY", line_seq, "an entry has exactly the seven public fields")
    seq = entry["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise Broken("MALFORMED_ENTRY", line_seq, "seq is not a positive integer")
    if not isinstance(entry["created_at"], str) or not TIMESTAMP_PATTERN.match(entry["created_at"]):
        raise Broken("NONCANONICAL_VALUE", seq, "created_at is not YYYY-MM-DDTHH:MM:SS.ffffffZ")
    if not isinstance(entry["event_type"], str) or not EVENT_PATTERN.match(entry["event_type"]):
        raise Broken("MALFORMED_ENTRY", seq, "event_type")
    if not isinstance(entry["subject"], str) or not 0 < len(entry["subject"]) <= 256:
        raise Broken("MALFORMED_ENTRY", seq, "subject")
    if not isinstance(entry["payload"], dict):
        raise Broken("MALFORMED_ENTRY", seq, "payload is not an object")
    for name in ("prev_hash", "entry_hash"):
        if not isinstance(entry[name], str) or not HASH_PATTERN.match(entry[name]):
            raise Broken("MALFORMED_ENTRY", seq, f"{name} is not 64 lowercase hex characters")
    return entry


def verify_lines(lines: Iterable[str], trusted_head: tuple[int, str] | None = None) -> dict[str, Any]:
    """Verify JSONL lines; returns a summary dict (status VERIFIED) or raises Broken at the first problem."""
    previous: dict[str, Any] | None = None
    count = 0
    trusted_seen = False
    for number, raw in enumerate(lines, start=1):
        line = raw[:-1] if raw.endswith("\n") else raw
        if not line.strip():
            raise Broken("MALFORMED_ENTRY", None, f"line {number} is empty")
        expected_seq = 1 if previous is None else previous["seq"] + 1
        try:
            parsed = parse_strict(line)
        except NotCanonical as exc:
            raise Broken("NONCANONICAL_VALUE", expected_seq, f"line {number}: {exc}") from exc
        entry = _check_entry(parsed, expected_seq)
        seq = entry["seq"]
        if canonical(entry) != line:
            raise Broken("NONCANONICAL_ENCODING", seq, f"line {number} is not in canonical form")
        if seq != expected_seq:
            if previous is not None and seq == previous["seq"]:
                code = "DUPLICATE_SEQ"
            elif seq < expected_seq:
                code = "SEQUENCE_ORDER"
            else:
                code = "SEQUENCE_GAP"
            raise Broken(code, seq, f"expected seq {expected_seq}, found {seq}")
        if seq == 1:
            if {k: entry[k] for k in GENESIS} != GENESIS:
                raise Broken("GENESIS_INVALID", 1, "entry 1 is not the protocol v1 genesis")
        elif entry["prev_hash"] != previous["entry_hash"]:  # type: ignore[index]
            raise Broken("PREV_HASH_MISMATCH", seq, f"prev_hash does not match entry {seq - 1}")
        if entry_hash(entry) != entry["entry_hash"]:
            raise Broken("ENTRY_HASH_MISMATCH", seq, "stored entry_hash differs from the recomputed hash")
        if trusted_head is not None and seq == trusted_head[0]:
            if entry["entry_hash"] != trusted_head[1]:
                raise Broken("TRUSTED_HEAD_MISMATCH", seq, "entry differs from the trusted head")
            trusted_seen = True
        previous = entry
        count += 1
    if previous is None:
        raise Broken("EMPTY_LEDGER", None, "no entries")
    if trusted_head is not None and not trusted_seen:
        raise Broken("TRUSTED_HEAD_MISSING", trusted_head[0], "the export is shorter than the trusted head")
    return {"entries": count, "head_seq": previous["seq"], "head_hash": previous["entry_hash"]}


def _read_url(base: str) -> Iterator[str]:
    url = base.rstrip("/") + "/api/v1/transparency/export"
    request = urllib.request.Request(url, headers={"Accept": "application/x-ndjson"})
    key = os.environ.get("HQAI_API_KEY", "")
    if key:
        request.add_header("X-API-Key", key)
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - operator-supplied URL
        for raw in response:
            yield raw.decode("utf-8")


def _trusted(text: str) -> tuple[int, str]:
    seq, _, digest = text.partition(":")
    if not seq.isdigit() or not HASH_PATTERN.match(digest):
        raise argparse.ArgumentTypeError("expected SEQ:HASH, e.g. 1427:" + "0" * 64)
    return int(seq), digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a transparency-ledger JSONL export offline.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("file", nargs="?", help="JSONL export (GET /api/v1/transparency/export)")
    source.add_argument("--url", help="API base URL to fetch the export from (key: HQAI_API_KEY)")
    parser.add_argument("--trusted-head", type=_trusted, help="SEQ:HASH recorded earlier; the chain must contain it")
    parser.add_argument("--expect-head", help="entry_hash the export must end with")
    args = parser.parse_args(argv)
    try:
        if args.url:
            lines: Iterable[str] = _read_url(args.url)
            summary = verify_lines(lines, args.trusted_head)
        else:
            with open(args.file, encoding="utf-8", newline="") as handle:
                summary = verify_lines(handle, args.trusted_head)
        if args.expect_head and summary["head_hash"] != args.expect_head.lower():
            raise Broken("TRUSTED_HEAD_MISMATCH", summary["head_seq"], "the export ends at a different head")
    except Broken as broken:
        print("BROKEN")
        print(f"seq: {broken.seq if broken.seq is not None else '-'}")
        print(f"reason: {broken.code}")
        print(f"detail: {broken.detail}")
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print("VERIFIED")
    print(f"entries: {summary['entries']}")
    print(f"head: {summary['head_seq']}:{summary['head_hash']}")
    print("genesis: OK")
    print("sequence: OK")
    print("hashes: OK")
    if args.trusted_head:
        print(f"trusted head: OK (entry {args.trusted_head[0]} unchanged)")
    print("scope: public chain only; source rows and private commitments need the server verification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
