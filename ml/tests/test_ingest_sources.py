"""Source validation of raw CSV parts (docs/data.md §1, "Source validation"), on files built in tmp_path.

A raw part is used only if it is non-empty, is not the XML error body of a failed download, carries exactly the
expected header and ends with a newline; invalid parts are skipped and reported, never fatal. These tests pin each
of the four checks, the folder lookup by dataset number and the DuckDB staging of the accepted parts (in-process,
no server)."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from hqai_ml.ingest.sources import EXPECTED_HEADERS, SourceFiles, _check_part, find_sources, part_number, stage_csv

HEADER_1 = ",".join(EXPECTED_HEADERS[1])
ROW_1 = ",".join(
    ["19.028V.021.7", "ТОО А", "ГКП Б", "O80.0", "Роды", "021", *["2025-02-01 10:00:00"] * 5, "", "", "", ""]
)


def write(path: Path, content: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def valid_part(path: Path, rows: int = 1) -> Path:
    return write(path, HEADER_1 + "\n" + "\n".join([ROW_1] * rows) + "\n")


def test_expected_headers_cover_the_four_ingested_datasets_with_unique_columns():
    """§1: datasets 1-4 are ingested; every header column is unique so `SELECT *` staging cannot collide."""
    assert sorted(EXPECTED_HEADERS) == [1, 2, 3, 4]
    for header in EXPECTED_HEADERS.values():
        assert len(set(header)) == len(header)
        assert header[-1] == "sdu_load_date"


def test_valid_part_passes_all_checks(tmp_path):
    assert _check_part(valid_part(tmp_path / "part.csv"), EXPECTED_HEADERS[1]) is None


def test_valid_part_with_utf8_bom_and_crlf_passes(tmp_path):
    """§1 check 3: the header is compared after stripping a UTF-8 BOM and the line ending."""
    path = write(tmp_path / "part.csv", b"\xef\xbb\xbf" + HEADER_1.encode() + b"\r\n" + ROW_1.encode() + b"\r\n")
    assert _check_part(path, EXPECTED_HEADERS[1]) is None


def test_empty_file_is_rejected(tmp_path):
    """§1 check 1: a zero-byte part is unusable."""
    assert _check_part(write(tmp_path / "part.csv", b""), EXPECTED_HEADERS[1]) == "empty file"


@pytest.mark.parametrize(
    "body",
    [
        '<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>NoSuchKey</Code></Error>\n',
        "<Error><Code>AccessDenied</Code><Message>Access Denied</Message></Error>\n",
        '  \n<?xml version="1.0"?><Error/>\n',
    ],
)
def test_xml_error_body_is_rejected(tmp_path, body):
    """§1 check 2: the XML error response of a failed S3 download is not a CSV."""
    reason = _check_part(write(tmp_path / "part.csv", body), EXPECTED_HEADERS[1])
    assert reason == "not a CSV (XML error response of a failed download)"


@pytest.mark.parametrize(
    "header",
    [
        HEADER_1.replace("hospital_mo", "hospital"),
        HEADER_1 + ",extra_column",
        ",".join(EXPECTED_HEADERS[1][:-1]),
        ",".join(reversed(EXPECTED_HEADERS[1])),
        ",".join(EXPECTED_HEADERS[3]),
        HEADER_1.upper(),
        HEADER_1.replace(",", ";"),
    ],
)
def test_header_must_match_exactly(tmp_path, header):
    """§1 check 3: renamed, missing, extra, reordered or differently delimited columns are rejected, and the reason
    quotes the header found."""
    reason = _check_part(write(tmp_path / "part.csv", header + "\n" + ROW_1 + "\n"), EXPECTED_HEADERS[1])
    assert reason is not None and reason.startswith("unexpected header: ")
    assert reason[len("unexpected header: ") :] == ",".join(header.strip().split(","))[:120]


def test_header_of_another_dataset_is_rejected_for_this_dataset(tmp_path):
    """§1 check 3: a dataset-3 part dropped into the dataset-1 folder must not be staged as referrals."""
    path = write(tmp_path / "part.csv", ",".join(EXPECTED_HEADERS[3]) + "\n")
    assert _check_part(path, EXPECTED_HEADERS[1]) is not None
    assert _check_part(path, EXPECTED_HEADERS[3]) is None


def test_header_only_file_needs_a_newline_too(tmp_path):
    """§1 checks 3 and 4: a header without a trailing newline is a truncated download, a header with one is a valid,
    empty part."""
    assert _check_part(write(tmp_path / "a.csv", HEADER_1), EXPECTED_HEADERS[1]) is not None
    assert _check_part(write(tmp_path / "b.csv", HEADER_1 + "\n"), EXPECTED_HEADERS[1]) is None


def test_missing_trailing_newline_is_rejected(tmp_path):
    """§1 check 4: a part whose last byte is not `\\n` is treated as a truncated download."""
    path = write(tmp_path / "part.csv", HEADER_1 + "\n" + ROW_1)
    assert _check_part(path, EXPECTED_HEADERS[1]) == "file does not end with a newline (truncated download?)"


def test_whitespace_only_file_is_rejected_as_bad_header(tmp_path):
    """§1 check 3: a non-empty file without a header line has an unexpected (empty) header."""
    assert _check_part(write(tmp_path / "part.csv", "\n\n"), EXPECTED_HEADERS[1]) == "unexpected header: "


def test_header_check_reads_only_the_head_of_a_large_part(tmp_path):
    """§1: validation opens 8 KiB plus the last two bytes, so a multi-gigabyte part is not read through."""
    path = valid_part(tmp_path / "big.csv", rows=2000)
    assert path.stat().st_size > 8192
    assert _check_part(path, EXPECTED_HEADERS[1]) is None


# --------------------------------------------------------------- find_sources
def test_find_sources_splits_valid_and_skipped_parts_with_reasons(tmp_path):
    """§1: invalid parts are skipped, not fatal, and listed with file name and reason for the manifest/report."""
    folder = tmp_path / "1 dataset"
    valid_part(folder / "Направления Часть 1 из 3.csv")
    write(folder / "Направления Часть 2 из 3.csv", "<Error/>\n")
    write(folder / "Направления Часть 3 из 3.csv", b"")
    write(folder / "notes.txt", "not a csv")
    result = find_sources(tmp_path, 1)
    assert result.dataset == 1
    assert [p.name for p in result.valid] == ["Направления Часть 1 из 3.csv"]
    assert result.skipped == [
        {"file": "Направления Часть 2 из 3.csv", "reason": "not a CSV (XML error response of a failed download)"},
        {"file": "Направления Часть 3 из 3.csv", "reason": "empty file"},
    ]


def test_find_sources_matches_the_folder_by_leading_dataset_number(tmp_path):
    """§1: the folder for dataset N starts with `N` followed by a word boundary (`1 dataset`, not `11 dataset`)."""
    valid_part(tmp_path / "11 dataset" / "x.csv")
    valid_part(tmp_path / "1 dataset" / "y.csv")
    valid_part(tmp_path / "10 other" / "z.csv")
    valid_part(tmp_path / "dataset 1" / "w.csv")
    assert [p.name for p in find_sources(tmp_path, 1).valid] == ["y.csv"]


def test_find_sources_without_a_folder_is_empty_not_an_error(tmp_path):
    result = find_sources(tmp_path, 2)
    assert result == SourceFiles(dataset=2)


def test_find_sources_orders_parts_by_name(tmp_path):
    """Staging concatenates parts in a deterministic order."""
    folder = tmp_path / "3 dataset"
    for name in ["Часть 3 из 3.csv", "Часть 1 из 3.csv", "Часть 2 из 3.csv"]:
        write(folder / name, ",".join(EXPECTED_HEADERS[3]) + "\n")
    names = [p.name for p in find_sources(tmp_path, 3).valid]
    assert names == ["Часть 1 из 3.csv", "Часть 2 из 3.csv", "Часть 3 из 3.csv"]


# ---------------------------------------------------------------- part_number
@pytest.mark.parametrize(
    ("file_name", "expected"),
    [("Отказы Часть 2 из 6.csv", 2), ("часть  10  ИЗ 12.csv", 10), ("single-file.csv", 1), ("Часть из 6.csv", 1)],
)
def test_part_number_reads_the_part_index_case_insensitively(file_name, expected):
    """§1: `Часть N из M` in the file name gives the part index; anything else is part 1."""
    assert part_number(file_name) == expected


# ------------------------------------------------------------------ stage_csv
def test_stage_csv_concatenates_valid_parts_as_varchar_with_source_file(tmp_path):
    """§1: parts are read with header, `,` delimiter, `"` quote/escape, all columns VARCHAR, plus source_file."""
    folder = tmp_path / "1 dataset"
    valid_part(folder / "Часть 1 из 2.csv", rows=2)
    quoted = ROW_1.replace("ГКП Б", '"ГКП ""Б"", г. Алматы"')
    write(folder / "Часть 2 из 2.csv", HEADER_1 + "\n" + quoted + "\n")
    con = duckdb.connect()
    try:
        assert stage_csv(con, "raw_referral", find_sources(tmp_path, 1)) == 3
        columns = {c[0]: c[1] for c in con.execute("DESCRIBE raw_referral").fetchall()}
        assert list(columns) == EXPECTED_HEADERS[1] + ["source_file"]
        assert set(columns.values()) == {"VARCHAR"}
        by_file = dict(con.execute("SELECT source_file, count(*) FROM raw_referral GROUP BY 1").fetchall())
        assert by_file == {"Часть 1 из 2.csv": 2, "Часть 2 из 2.csv": 1}
        hospital = con.execute("SELECT hospital_mo FROM raw_referral WHERE source_file LIKE '%2 из 2%'").fetchone()[0]
        assert hospital == 'ГКП "Б", г. Алматы'
    finally:
        con.close()


def test_stage_csv_without_valid_parts_fails_loudly(tmp_path):
    """§1: a dataset with no usable part stops the run and names the skipped files."""
    folder = tmp_path / "1 dataset"
    write(folder / "Часть 1 из 1.csv", b"")
    con = duckdb.connect()
    try:
        with pytest.raises(FileNotFoundError, match="dataset 1: no valid CSV files .*empty file"):
            stage_csv(con, "raw_referral", find_sources(tmp_path, 1))
    finally:
        con.close()
