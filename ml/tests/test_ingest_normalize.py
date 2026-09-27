"""Cleaning rules of the ingest layer (docs/data.md §2.1-2.2), protected function by function.

The pure Python helpers in hqai_ml.ingest.normalize decide how every organization and region name is displayed and
matched; a silent change there re-links hospitals to other ERSB rows or regions. Each test names the rule it guards.
The last section runs the SQL `clean` macro and the staging queries in an in-process DuckDB connection (no server,
no files) because the whitespace/BOM/empty->NULL and ICD upper-casing rules live in SQL, not in Python."""

from __future__ import annotations

import unicodedata

import duckdb
import pytest

from hqai_ml.ingest.normalize import (
    LEGAL_FORM_STOPWORDS,
    clean_text,
    core_key,
    name_key,
    normalize_name,
    number_tokens,
    register_name_map,
    short_org_name,
)
from hqai_ml.ingest.sources import EXPECTED_HEADERS
from hqai_ml.ingest.staging import build_name_map, build_stg_referral, build_stg_refusal, create_macros

NBSP, FIGURE_SPACE, NARROW_NBSP, BOM = "\u00a0", "\u2007", "\u202f", "\ufeff"


# ------------------------------------------------------------------ §2.1 clean
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  ТОО  Х ", "ТОО Х"),
        (f"ТОО{NBSP}{NBSP}Х", "ТОО Х"),
        (f"{FIGURE_SPACE}ТОО{NARROW_NBSP}Х{FIGURE_SPACE}", "ТОО Х"),
        ("ТОО\t\r\nХ", "ТОО Х"),
        ("Х", "Х"),
    ],
)
def test_clean_text_collapses_all_whitespace_runs_and_trims(raw, expected):
    """§2.1: all whitespace runs (incl. NBSP, narrow/figure spaces) -> one space, then trim."""
    assert clean_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", f"{NBSP}{NBSP}", "\t\n", None])
def test_clean_text_empty_becomes_none(raw):
    """§2.1: empty string (after trimming) -> NULL; NULL stays NULL."""
    assert clean_text(raw) is None


# --------------------------------------------------------- §2.2 normalize_name
def test_normalize_name_unifies_double_quotes():
    """§2.2 step 2: « » „ “ ” ‟ ″ 〝 〞 ＂ -> the ASCII double quote."""
    assert normalize_name("ТОО «А» „Б“ ”В‟ ″Г″ 〝Д〞 ＂Е＂") == 'ТОО "А" "Б" "В" "Г" "Д" "Е"'


def test_normalize_name_unifies_single_quotes():
    """§2.2 step 2: ‘ ’ ‚ ‛ ` ´ -> the ASCII apostrophe."""
    assert normalize_name("‘а’ ‚б‛ `в´") == "'а' 'б' 'в'"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Oбласть", "Область"),
        ("РУДHЕHСКИЙ", "РУДНЕНСКИЙ"),
        ("Ақтөбе Oблысы", "Ақтөбе Облысы"),
        ("Бoльницa", "Больница"),
    ],
)
def test_latin_homoglyphs_inside_a_cyrillic_word_become_cyrillic(raw, expected):
    """§2.2 step 3a: Latin O C A E H P K M T X B a c e o p x inside a Cyrillic word -> Cyrillic."""
    assert normalize_name(raw) == expected


def test_cyrillic_lookalikes_inside_a_latin_word_become_latin():
    """§2.2 step 3b: a word whose Latin letters are not all look-alikes but whose Cyrillic letters are -> Latin."""
    assert normalize_name("ТОО «МЕD»") == 'ТОО "MED"'
    assert normalize_name("МЕD") == "MED"
    assert normalize_name("МЕD").isascii()


def test_word_mixing_distinct_letters_of_both_alphabets_is_left_unchanged():
    """§2.2: a word with non-look-alike letters of both alphabets (МЕDИКЕР) is not repaired."""
    assert normalize_name("МЕDИКЕР") == "МЕDИКЕР"


@pytest.mark.parametrize("word", ["MED", "COBA", "СОВА", "Область"])
def test_single_alphabet_words_are_never_touched(word):
    """§2.2 step 3: homoglyph repair applies only to words that mix the two alphabets."""
    assert normalize_name(word) == word


def test_homoglyph_repair_is_per_word_not_per_string():
    """§2.2 step 3: each word decides for itself, so a Latin brand and a Cyrillic word coexist."""
    assert normalize_name("Oбласть МЕD МЕDИКЕР") == "Область MED МЕDИКЕР"


def test_normalize_name_runs_clean_before_and_after():
    """§2.2 steps 1 and 4: whitespace is collapsed at both ends of the pipeline; empty -> NULL."""
    assert normalize_name(f"  ТОО{NBSP}«Х»  ") == 'ТОО "Х"'
    assert normalize_name("   ") is None
    assert normalize_name(None) is None


# --------------------------------------------------------------- §2.2 name_key
def test_name_key_casefolds_and_maps_yo_to_ye():
    """§2.2 matching key: case-folded, ё -> е."""
    assert name_key("Ёлка") == name_key("ЕЛКА") == "елка"


def test_name_key_turns_quotes_number_sign_and_punctuation_into_spaces():
    """§2.2 matching key: every non-word character (quotes, №, punctuation) -> space, collapsed."""
    assert name_key(" ТОО  «Ёлка-Плюс»  №14 ") == "тоо елка плюс 14"
    assert name_key('ГКП "Больница", г. Алматы') == "гкп больница г алматы"


def test_name_key_treats_underscore_as_separator():
    """§2.2 matching key: `_` counts as a word character for \\w but is a separator for names."""
    assert name_key("ГКП_на_ПХВ") == "гкп на пхв"


def test_name_key_matches_spellings_that_differ_only_by_noise():
    """§2.2: the key is the basis of every exact name match, so cosmetic variants must collide."""
    variants = ["ТОО «Медикер»", 'ТОО "МЕДИКЕР"', f"тоо{NBSP}Медикер", "ТОО Медикер."]
    assert len({name_key(v) for v in variants}) == 1


def test_name_key_applies_homoglyph_repair_first():
    """§2.2: the key is built from the normalized name, so Oбласть and Область share a key."""
    assert name_key("Oбласть") == name_key("Область") == "область"


def test_name_key_of_punctuation_only_is_none():
    """§2.2: a value that is only quotes/punctuation has no key (NULL), not an empty string."""
    assert name_key("«»") is None
    assert name_key(None) is None


# --------------------------------------------------------------- §2.2 core_key
def test_core_key_drops_legal_form_words():
    """§2.2 core key: legal-form/administrative words are removed so boilerplate cannot dominate fuzzy scores."""
    key = name_key('Товарищество с ограниченной ответственностью "Адалдент"')
    assert core_key(key) == "адалдент"


def test_core_key_makes_boilerplate_only_names_distinguishable():
    """§2.2 core key: two ТОО names with different distinctive tokens must not share a core."""
    a = core_key(name_key('ТОО "Адалдент"'))
    b = core_key(name_key('ТОО "ТТи К"'))
    assert a == "адалдент"
    assert b == "тти к"


def test_core_key_removes_diacritics():
    """§2.2 core key: diacritics removed (ẏ -> y, й -> и) before fuzzy matching."""
    assert core_key("ẏ") == "y"
    assert core_key("район") == "раион"


def test_core_key_of_empty_is_empty_string():
    """core_key is used inside rapidfuzz comparisons and must return a string, never None."""
    assert core_key(None) == ""
    assert core_key("") == ""


def test_core_key_keeps_the_full_legal_form_phrase_out():
    """§2.2 core key: `на праве хозяйственного ведения`, `управления здравоохранения`, `акимата`, `области`,
    `города` are all dropped."""
    key = name_key(
        'ГКП на ПХВ "Городская больница №1" Управления здравоохранения акимата города Алматы Алматинской области'
    )
    assert core_key(key) == "городская больница 1 алматы алматинскои"


def test_legal_form_stopwords_are_lowercase_without_marks():
    """The stopword list is compared against case-folded, mark-stripped tokens; a capital or a й would never match."""
    assert all(w == w.casefold() for w in LEGAL_FORM_STOPWORDS)
    assert all(not unicodedata.combining(c) for w in LEGAL_FORM_STOPWORDS for c in unicodedata.normalize("NFKD", w))
    assert "хозяиственного" in LEGAL_FORM_STOPWORDS


def test_number_tokens_extracts_every_digit_run():
    """§3 ERSB matching: `№14` and `№15` differ by number tokens, so the fuzzy rule rejects them."""
    assert number_tokens("городская поликлиника 14") == frozenset({"14"})
    assert number_tokens("гп 14 п 3") == frozenset({"14", "3"})
    assert number_tokens("гп 14") != number_tokens("гп 15")
    assert number_tokens("без номера") == frozenset()


# ------------------------------------------------------------- short_org_name
def test_short_org_name_abbreviates_legal_forms_case_insensitively():
    """Display form for the UI: standard abbreviations of legal forms."""
    long = "Государственное коммунальное предприятие на праве хозяйственного ведения"
    assert short_org_name(f'{long} "Больница" Управления здравоохранения') == 'ГКП на ПХВ "Больница" УЗ'
    assert short_org_name('товарищество с ограниченной ответственностью "Х"') == 'ТОО "Х"'
    assert short_org_name('Некоммерческое акционерное общество "Y"') == 'НАО "Y"'


def test_short_org_name_of_missing_name_is_a_dash():
    assert short_org_name(None) == "—"
    assert short_org_name("") == "—"


# ------------------------------------------ SQL clean macro and staging (DuckDB in-process)
@pytest.fixture
def con():
    connection = duckdb.connect()
    create_macros(connection)
    yield connection
    connection.close()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  a   b ", "a b"),
        (f"{BOM}a{NBSP}{NBSP}b{FIGURE_SPACE}", "a b"),
        (f"a{NARROW_NBSP}b", "a b"),
        ("", None),
        ("   ", None),
        (f"{BOM}", None),
        (None, None),
    ],
)
def test_sql_clean_macro_whitespace_bom_and_empty_to_null(con, raw, expected):
    """§2.1: the `clean` macro applied to every text field: whitespace incl. NBSP/figure/narrow spaces and BOM -> one
    space, trim, empty -> NULL."""
    assert con.execute("SELECT clean(?)", [raw]).fetchone()[0] == expected


def _varchar_table(con: duckdb.DuckDBPyConnection, name: str, columns: list[str], rows: list[list]) -> None:
    ddl = ", ".join(f'"{c}" VARCHAR' for c in columns)
    con.execute(f"CREATE TABLE {name} ({ddl})")
    placeholders = ", ".join("?" for _ in columns)
    con.executemany(f"INSERT INTO {name} VALUES ({placeholders})", rows)


def _row(columns: list[str], **values) -> list:
    return [values.get(c) for c in columns]


@pytest.fixture
def staged(con):
    """Three tiny raw tables with the real dataset headers plus stage_csv's `source_file`; enough for name_map and the
    two staging queries."""
    ref_cols, refusal_cols, ersb_cols = (EXPECTED_HEADERS[d] + ["source_file"] for d in (1, 3, 4))
    _varchar_table(
        con,
        "raw_referral",
        ref_cols,
        [
            _row(
                ref_cols,
                hospitalization_code=" 19.028V.021.7 ",
                referring_mo="  ТОО  «МЕD» ",
                hospital_mo="ГКП Oбласть",
                icd10_ref_diag_code=" o80.0 ",
                diagnosis_name="",
                bed_profile=f"{NBSP}",
                registration_dt="2025-02-01 10:00:00",
                planned_dt="2025-02-10 00:00:00",
                sdu_load_date="2025-04-01 00:00:00",
            )
        ],
    )
    _varchar_table(
        con,
        "raw_refusal",
        refusal_cols,
        [
            _row(
                refusal_cols,
                source_file="Отказы Часть 2 из 6.csv",
                region_in="Aлматинская область",
                org_in="ГКП Область",
                icd10="m42.1",
                icd_name="   ",
                refuse_dt="2025-02-02 10:00:00",
                amount="12.50",
                sdu_load_date="2025-04-01 00:00:00",
            )
        ],
    )
    _varchar_table(con, "raw_ersb", ersb_cols, [_row(ersb_cols, medicine_organization='ГКП "Область"')])
    build_name_map(con)
    build_stg_referral(con)
    build_stg_refusal(con)
    return con


def test_staging_upper_cases_icd_codes(staged):
    """§2.1: codes (icd10_code) are additionally upper-cased, in dataset 1 and dataset 3 alike."""
    assert staged.execute("SELECT icd10_code FROM stg_referral").fetchone()[0] == "O80.0"
    assert staged.execute("SELECT icd10_code FROM stg_refusal").fetchone()[0] == "M42.1"


def test_staging_turns_empty_and_whitespace_only_text_into_null(staged):
    """§2.1: empty string and whitespace-only values (incl. NBSP) -> NULL."""
    diagnosis, bed_profile = staged.execute("SELECT diagnosis_name, bed_profile FROM stg_referral").fetchone()
    assert diagnosis is None and bed_profile is None
    assert staged.execute("SELECT icd_name FROM stg_refusal").fetchone()[0] is None


def test_staging_splits_the_hospitalization_code_after_cleaning(staged):
    """§3: region_code, org_code, profile_code are parts 1-3 of the cleaned hospitalization_code."""
    row = staged.execute("SELECT region_code, org_code, profile_code, seq_no FROM stg_referral").fetchone()
    assert row == ("19", "028V", "021", "7")


def test_staging_reads_the_part_number_from_the_source_file_name(staged):
    """§1: dataset-3 rows remember which CSV part they came from (source_part)."""
    assert staged.execute("SELECT source_part FROM stg_refusal").fetchone()[0] == 2


def test_staging_joins_normalized_names_and_keys_through_name_map(staged):
    """§2.2: names are normalized once per distinct spelling (name_map) and joined back as name + key."""
    referring, hospital, key = staged.execute(
        "SELECT referring_mo, hospital_mo, hospital_key FROM stg_referral"
    ).fetchone()
    assert referring == 'ТОО "MED"'
    assert hospital == "ГКП Область"
    assert key == "гкп область"
    org_in_key = staged.execute("SELECT org_in_key FROM stg_refusal").fetchone()[0]
    assert org_in_key == key, "dataset-1 hospital and dataset-3 org_in must meet on the same key"
    assert staged.execute("SELECT region_in FROM stg_refusal").fetchone()[0] == "Алматинская область"


def test_register_name_map_covers_every_distinct_raw_value_and_skips_null(con):
    """name_map has one row per distinct raw spelling; NULLs are not mapped (the join leaves them NULL)."""
    con.execute("CREATE TABLE t (v VARCHAR)")
    con.executemany("INSERT INTO t VALUES (?)", [["ТОО «МЕD»"], ["ТОО «МЕD»"], ["Oбласть"], [None]])
    assert register_name_map(con, "SELECT DISTINCT v FROM t") == 2
    rows = dict(con.execute("SELECT raw, (name, key) FROM name_map ORDER BY raw").fetchall())
    assert rows == {"ТОО «МЕD»": ('ТОО "MED"', "тоо med"), "Oбласть": ("Область", "область")}
