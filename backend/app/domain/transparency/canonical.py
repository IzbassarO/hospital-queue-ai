"""Canonical JSON of the transparency ledger, contract `hqai-canonical-json-v1` (docs/transparency-ledger.md §3).

The bytes produced here are hashed, so the same value must give the same bytes in every runtime that verifies the
ledger: this module, the standalone stdlib verifier (tools/ledger_verify.py) and the browser
(frontend/src/verify/canonical.ts). None of them relies on its runtime's JSON serializer; each implements the
rules below, and all three are tested against docs/transparency-ledger-vectors.json.

The contract is a strict subset of JSON:

- values: null, true, false, integers in [-(2^53-1), 2^53-1], strings, arrays, objects; floats are rejected
  (a float has no single decimal spelling shared by all runtimes), so is everything else;
- object keys match ``[a-z][a-z0-9_]{0,63}``: ASCII only, so sorting by code point, by UTF-16 unit and by byte is
  the same order; keys are sorted ascending and must be unique;
- strings are Unicode scalar values encoded as UTF-8; lone surrogates and U+0000 are rejected (PostgreSQL JSONB
  cannot store U+0000); ``"`` and ``\\`` are escaped with a backslash, U+0008/0009/000A/000C/000D as \\b \\t \\n \\f
  \\r, every other code point below U+0020 as \\u00xx with lowercase hex, and everything else is written as itself
  (no escaping of "/", of non-ASCII, of U+2028/U+2029 or of U+007F);
- no whitespace anywhere; arrays keep their order;
- nesting depth at most 32.

Timestamps are not a JSON type: they are strings in one form, ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` (UTC, always six
fractional digits), produced by :func:`timestamp`. Text is never normalised: "" and null stay different, and
Unicode normalisation forms are kept as given.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

MAX_SAFE_INTEGER = 2**53 - 1
MAX_DEPTH = 32
KEY_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_SHORT_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r"}


class CanonicalError(ValueError):
    """A value outside the canonical subset. ``code`` is machine-readable and shared with the other verifiers."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _string(value: str) -> str:
    if "\x00" in value:
        raise CanonicalError("NUL_IN_STRING", "U+0000 is not allowed in canonical strings")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalError("LONE_SURROGATE", "strings must be Unicode scalar values") from exc
    out = ['"']
    for char in value:
        escaped = _SHORT_ESCAPES.get(char)
        if escaped is not None:
            out.append(escaped)
        elif char < " ":
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _encode(value: Any, depth: int, out: list[str]) -> None:
    if depth > MAX_DEPTH:
        raise CanonicalError("TOO_DEEP", f"nesting deeper than {MAX_DEPTH}")
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, int):
        if not -MAX_SAFE_INTEGER <= value <= MAX_SAFE_INTEGER:
            raise CanonicalError("INTEGER_OUT_OF_RANGE", f"{value} is outside ±(2^53-1)")
        out.append(str(int(value)))
    elif isinstance(value, float):
        raise CanonicalError("FLOAT_NOT_ALLOWED", f"floating-point number {value!r}")
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, (list, tuple)):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, depth + 1, out)
        out.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str) or not KEY_PATTERN.match(key):
                raise CanonicalError("INVALID_KEY", f"object key {key!r} is not [a-z][a-z0-9_]{{0,63}}")
        out.append("{")
        for i, key in enumerate(sorted(value)):
            if i:
                out.append(",")
            out.append(_string(key))
            out.append(":")
            _encode(value[key], depth + 1, out)
        out.append("}")
    else:
        raise CanonicalError("UNSUPPORTED_TYPE", f"{type(value).__name__} is not a canonical JSON value")


def canonical_text(value: Any) -> str:
    """The canonical JSON text of ``value``; raises :class:`CanonicalError` outside the subset."""
    out: list[str] = []
    _encode(value, 0, out)
    return "".join(out)


def canonical_bytes(value: Any) -> bytes:
    return canonical_text(value).encode("utf-8")


def timestamp(value: dt.datetime) -> str:
    """The one canonical spelling of an instant: UTC, microseconds, ``Z``. Naive datetimes are rejected."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalError("NAIVE_TIMESTAMP", "timestamps must carry a time zone")
    utc = value.astimezone(dt.UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond:06d}Z"


def parse_timestamp(text: str) -> dt.datetime:
    if not isinstance(text, str) or not TIMESTAMP_PATTERN.match(text):
        raise CanonicalError("INVALID_TIMESTAMP", f"{text!r} is not YYYY-MM-DDTHH:MM:SS.ffffffZ")
    return dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=dt.UTC)


def _reject_float(text: str) -> Any:
    raise CanonicalError("FLOAT_NOT_ALLOWED", f"floating-point number {text}")


def _reject_constant(text: str) -> Any:
    raise CanonicalError("MALFORMED_JSON", f"{text} is not JSON")


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalError("DUPLICATE_KEY", f"duplicate object key {key!r}")
        result[key] = value
    return result


def parse_strict(text: str) -> Any:
    """Parse JSON text into canonical-subset values: floats, NaN/Infinity and duplicate keys are rejected. The
    result still has to pass :func:`canonical_text` (key pattern, integer range, strings)."""
    try:
        value = json.loads(
            text, parse_float=_reject_float, parse_constant=_reject_constant, object_pairs_hook=_unique_keys
        )
    except CanonicalError:
        raise
    except ValueError as exc:
        raise CanonicalError("MALFORMED_JSON", str(exc)) from exc
    canonical_text(value)
    return value
