"""Text normalization for organization and region names.

Normalization runs in Python over the *distinct* raw values only (a few
thousand), and the result is joined back in DuckDB via a mapping table.
"""
import re
import unicodedata

import duckdb
import pandas as pd

# Latin letters that look identical to Cyrillic ones.
_LATIN_HOMOGLYPHS = "OCAEHPKMTXBaceopx"
_CYRILLIC_HOMOGLYPHS = "ОСАЕНРКМТХВасеорх"
_LATIN_TO_CYRILLIC = str.maketrans(_LATIN_HOMOGLYPHS, _CYRILLIC_HOMOGLYPHS)
_CYRILLIC_TO_LATIN = str.maketrans(_CYRILLIC_HOMOGLYPHS, _LATIN_HOMOGLYPHS)

_CYRILLIC = re.compile(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]")
_LATIN = re.compile(r"[A-Za-z]")
_WORD = re.compile(r"[^\W\d_]+")
_WHITESPACE = re.compile(r"\s+")  # Python's \s includes NBSP and other unicode spaces
_DOUBLE_QUOTES = str.maketrans({c: '"' for c in "«»„“”‟″〝〞＂"})
_SINGLE_QUOTES = str.maketrans({c: "'" for c in "‘’‚‛`´"})
_NON_WORD = re.compile(r"[^\w]+")


def clean_text(value: str | None) -> str | None:
    """Trim and collapse all whitespace; empty -> None."""
    if value is None:
        return None
    value = _WHITESPACE.sub(" ", value).strip()
    return value or None


def _fix_homoglyphs(match: re.Match) -> str:
    word = match.group(0)
    if not (_CYRILLIC.search(word) and _LATIN.search(word)):
        return word
    latin_only = [c for c in word if _LATIN.match(c) and c not in _LATIN_HOMOGLYPHS]
    cyrillic_only = [c for c in word if _CYRILLIC.match(c) and c not in _CYRILLIC_HOMOGLYPHS]
    if latin_only and not cyrillic_only:
        # a Latin word with Cyrillic look-alikes, e.g. "МЕD" -> "MED"
        return word.translate(_CYRILLIC_TO_LATIN)
    # a Cyrillic word with Latin look-alikes, e.g. "Oбласть" -> "Область"
    return word.translate(_LATIN_TO_CYRILLIC)


def normalize_name(value: str | None) -> str | None:
    """Display form of an organization/region name."""
    value = clean_text(value)
    if value is None:
        return None
    value = value.translate(_DOUBLE_QUOTES).translate(_SINGLE_QUOTES)
    value = _WORD.sub(_fix_homoglyphs, value)
    return clean_text(value)


def name_key(value: str | None) -> str | None:
    """Matching key: normalized, case-folded, ё→е, punctuation and quotes removed."""
    value = normalize_name(value)
    if value is None:
        return None
    value = value.casefold().replace("ё", "е")
    return clean_text(_NON_WORD.sub(" ", value).replace("_", " "))


def _strip_marks(value: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch))


# Legal-form and administrative boilerplate. It dominates long names and makes fuzzy
# scores meaningless ("ТОО "Адалдент"" vs "ТОО "ТТи К"" scores 94), so fuzzy matching
# compares only the remaining, distinctive tokens.
LEGAL_FORM_STOPWORDS = frozenset(_strip_marks(w) for w in """
    товарищество товарищества тоо ограниченной ответственностью
    государственное государственного государственном коммунальное коммунального казенное казенного
    предприятие предприятия гкп кгп гккп кгкп пхв ргп на праве хозяйственного ведения введения
    при управления управлении управление здравоохранения общественного акимата области города г
    учреждение учреждения республиканское акционерное общество ао филиал филиала некоммерческое нао
    корпоративный фонд и с по
""".split())
_NUMBER = re.compile(r"\d+")


def core_key(key: str | None) -> str:
    """Distinctive part of a name_key: diacritics removed (ẏ→y, й→и), legal-form words dropped."""
    if not key:
        return ""
    return " ".join(t for t in _strip_marks(key).split() if t not in LEGAL_FORM_STOPWORDS)


def number_tokens(value: str) -> frozenset[str]:
    return frozenset(_NUMBER.findall(value))


_LEGAL_FORM_ABBREVIATIONS = [
    (r"Некоммерческое акционерное общество", "НАО"),
    (r"Акционерное общество", "АО"),
    (r"Товариществ[оа] с ограниченной ответственностью", "ТОО"),
    (r"на праве хозяйственного ведения", "на ПХВ"),
    (r"управлени[яе] здравоохранения", "УЗ"),
    (r"Республиканское государственное предприятие на праве хозяйственного ведения", "РГП на ПХВ"),
    (r"Государственное коммунальное предприятие на праве хозяйственного ведения", "ГКП на ПХВ"),
    (r"Коммунальное государственное предприятие на праве хозяйственного ведения", "КГП на ПХВ"),
    (r"Государственное коммунальное казенное предприятие", "ГККП"),
    (r"Коммунальное государственное казенное предприятие", "КГКП"),
    (r"Государственное коммунальное предприятие", "ГКП"),
    (r"Коммунальное государственное предприятия?", "КГП"),
    (r"Государственное учреждение", "ГУ"),
    (r"Учреждение", "У"),
]


def short_org_name(name: str | None) -> str:
    """Display form: standard abbreviations of legal forms (ТОО, ГКП на ПХВ, …)."""
    s = name or "—"
    for pattern, abbr in _LEGAL_FORM_ABBREVIATIONS:
        s = re.sub(pattern, abbr, s, flags=re.IGNORECASE)
    return s


def register_name_map(con: duckdb.DuckDBPyConnection, sql_distinct_values: str, table: str = "name_map") -> int:
    """Create `table(raw, name, key)` for every distinct value returned by the SQL."""
    raw = [r[0] for r in con.execute(sql_distinct_values).fetchall() if r[0] is not None]
    df = pd.DataFrame({"raw": raw, "name": [normalize_name(v) for v in raw], "key": [name_key(v) for v in raw]}, dtype=object)
    con.register("_name_map_df", df)
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT raw::VARCHAR AS raw, name::VARCHAR AS name, key::VARCHAR AS key FROM _name_map_df")
    con.unregister("_name_map_df")
    return len(df)
