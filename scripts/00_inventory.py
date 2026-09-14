#!/usr/bin/env python3
"""Step 1 — data inventory of data/raw/.

Profiles every dataset folder (files, encodings, schema, row counts, nulls,
date ranges, categorical distinct counts, id uniqueness, multi-part layout)
and writes reports/00_inventory.md. No modeling, no business aggregation.

Memory: CSVs are never loaded into pandas. DuckDB reads them straight from
disk into a throwaway on-disk DuckDB database in a temp directory (deleted at
the end), with a memory limit, so large folders spill to disk instead of RAM.
XLSX files are small and are read with pandas/openpyxl.

data/raw/ is read-only for this script.

Run:  .venv/bin/python scripts/00_inventory.py
"""
from __future__ import annotations

import codecs
import csv
import datetime as dt
import io
import math
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
REPORT = ROOT / "reports" / "00_inventory.md"

DUCKDB_MEMORY_LIMIT = "4GB"

DATASET_TITLES = {
    1: "Referrals for planned hospitalization (IS BG)",
    2: "Patients currently waiting for planned hospitalization (IS BG)",
    3: "Refusals of planned hospitalization at the admission unit (IS BG)",
    4: "Treated cases per medical organization (ERSB)",
    5: "Vaccination facts",
    6: "Vaccination refusals and contraindications",
    7: "Newly diagnosed oncology patients",
    8: "Advanced-stage malignant neoplasms by localization",
}
CORE = {1, 2, 3, 4}

PSEUDO_NULLS = ("", "nat", "nan", "null", "none", "n/a", "-")
DATE_NAME_RE = re.compile(r"(_dt$|^dt_|date|_at$)")
ID_NAME_RE = re.compile(r"(^id$|_id$|^id_|hospitalization_code|number|card|seq|_no$)")
CAT_NAME_RE = re.compile(
    r"(region|(^|_)mo(_|$)|org|organi[sz]ation|clinic|hospital|status|profile|department|bed_prof"
    r"|icd|diag|territorial|purpose|finance|reason|contraindication|plan_code|localization"
    r"|cause|resident|insured|benefit|social|group|circumstances|invalid|place)"
)
PART_RE = re.compile(r"Часть\s+(\d+)\s+из\s+(\d+)", re.IGNORECASE)

MIN_PLAUSIBLE_DATE = "2000-01-01"

warnings_global: list[str] = []


# ----------------------------------------------------------------- helpers
def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def fmt_int(n) -> str:
    return "—" if n is None else f"{int(n):,}".replace(",", " ")


def pct(a, b) -> str:
    if not b:
        return "—"
    return f"{100.0 * a / b:.1f}%"


def md_cell(v, width: int = 60) -> str:
    if v is None:
        return "∅"
    s = str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    if len(s) > width:
        s = s[: width - 1] + "…"
    return s


def md_table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return out


def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def ts_expr(col: str) -> str:
    c = q(col)
    return (
        f"coalesce(TRY_CAST({c} AS TIMESTAMP), try_strptime({c}, '%d.%m.%Y %H:%M:%S'), "
        f"try_strptime({c}, '%d.%m.%Y'))"
    )


SEVERITY_RULES = [
    ("critical", re.compile(r"download failed|parts are missing|not a 'currently|calendar|months|× more|inventory failed"
                            r"|mixed encod|mixed delim|malformed|do NOT share|folder is empty")),
    ("minor", re.compile(r"whitespace|pseudo-null|completely empty|null/pseudo-null|leading zeros|informational")),
]


def severity(msg: str) -> str:
    for level, rx in SEVERITY_RULES:
        if rx.search(msg):
            return level
    return "notable"


def warn(ds: int, msg: str) -> None:
    warnings_global.append(f"**{'Core datasets' if ds == 0 else f'Dataset {ds}'}:** {msg}")


# ------------------------------------------------------------ file sniffing
def classify_file(path: Path) -> tuple[str, str]:
    """Return (status, note). status in ok | empty | invalid."""
    size = path.stat().st_size
    if size == 0:
        return "empty", "0 bytes"
    with open(path, "rb") as f:
        head = f.read(4096)
    stripped = head.lstrip(b"\xef\xbb\xbf").lstrip()
    if path.suffix.lower() == ".csv" and (stripped.startswith(b"<?xml") or stripped.startswith(b"<Error")):
        text = head.decode("utf-8", "replace")
        code = re.search(r"<Code>(.*?)</Code>", text)
        actual = re.search(r"<ActualObjectSize>(\d+)</ActualObjectSize>", text)
        note = f"not a CSV: XML error response ({code.group(1) if code else 'unknown'})"
        if actual:
            note += f"; server object size {fmt_size(int(actual.group(1)))} — download failed"
        return "invalid", note
    if path.suffix.lower() == ".xlsx" and not head.startswith(b"PK"):
        return "invalid", "not a valid XLSX (zip) file"
    return "ok", ""


def detect_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        chunk = f.read(4 * 1024 * 1024)
    if chunk.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(chunk, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def sniff_delimiter(path: Path, encoding: str) -> str:
    with open(path, encoding="utf-8-sig" if encoding.startswith("utf-8") else encoding,
              errors="replace", newline="") as f:
        sample = f.read(256 * 1024)
    best, best_score = ",", -1.0
    for d in [",", ";", "\t", "|"]:
        rows = list(csv.reader(io.StringIO(sample), delimiter=d))[:-1][:200]
        if len(rows) < 2:
            continue
        n_header = len(rows[0])
        if n_header < 2:
            continue
        consistent = sum(1 for r in rows if len(r) == n_header) / len(rows)
        score = consistent * 1000 + n_header
        if score > best_score:
            best, best_score = d, score
    return best


def read_header(path: Path, encoding: str, delim: str) -> list[str]:
    with open(path, encoding="utf-8-sig" if encoding.startswith("utf-8") else encoding,
              errors="replace", newline="") as f:
        return next(csv.reader(f, delimiter=delim))


def transcode_to_utf8(src: Path, dst: Path, encoding: str) -> None:
    dec = codecs.getincrementaldecoder(encoding)()
    with open(src, "rb") as fi, open(dst, "w", encoding="utf-8", newline="") as fo:
        while block := fi.read(16 * 1024 * 1024):
            fo.write(dec.decode(block))
        fo.write(dec.decode(b"", final=True))


# ------------------------------------------------------------------ loading
def load_csv_dataset(con, ds: int, table: str, files: list[dict], tmpdir: Path) -> dict:
    info: dict = {"rejects": 0, "schema_same": True, "sniffed_types": {}}
    headers = {}
    read_paths = []
    for fi in files:
        fi["encoding"] = detect_encoding(fi["path"])
        fi["delimiter"] = sniff_delimiter(fi["path"], fi["encoding"])
        headers[fi["name"]] = read_header(fi["path"], fi["encoding"], fi["delimiter"])
        if fi["encoding"] == "cp1251":
            dst = tmpdir / f"ds{ds}_{len(read_paths)}.csv"
            transcode_to_utf8(fi["path"], dst, "cp1251")
            fi["read_path"] = dst
        else:
            fi["read_path"] = fi["path"]
        read_paths.append(fi["read_path"])

    encs = {("utf-8" if f["encoding"].startswith("utf-8") else f["encoding"]) for f in files}
    if len(encs) > 1:
        warn(ds, f"mixed encodings across parts: {sorted(encs)}")
    delims = {f["delimiter"] for f in files}
    if len(delims) > 1:
        warn(ds, f"mixed delimiters across parts: {sorted(delims)}")

    header_sets = {tuple(h) for h in headers.values()}
    info["schema_same"] = len(header_sets) == 1
    info["headers"] = headers
    if not info["schema_same"]:
        warn(ds, "CSV parts do NOT share one header; loaded with union_by_name")

    paths_sql = "[" + ", ".join(sql_str(str(p)) for p in read_paths) + "]"
    delim = files[0]["delimiter"]
    common = f"delim={sql_str(delim)}, header=true, quote='\"', escape='\"'"
    if not info["schema_same"]:
        common += ", union_by_name=true"

    # DuckDB's own type guess from its default sample (for reference).
    try:
        for name, typ, *_ in con.execute(f"DESCRIBE SELECT * FROM read_csv({paths_sql}, {common})").fetchall():
            info["sniffed_types"][name] = typ
    except duckdb.Error as e:
        info["sniff_error"] = str(e).splitlines()[0]

    # Load everything as VARCHAR so no value is silently coerced (leading zeros etc.).
    base = f"read_csv({paths_sql}, {common}, all_varchar=true, filename=true"
    try:
        con.execute(f"CREATE TABLE {table} AS SELECT * FROM {base})")
    except duckdb.Error as e:
        info["strict_error"] = str(e).splitlines()[0][:300]
        warn(ds, f"strict CSV parse failed ({info['strict_error'][:150]}); reloaded skipping bad rows")
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(
            f"CREATE TABLE {table} AS SELECT * FROM {base}, ignore_errors=true, store_rejects=true, "
            f"rejects_table='rej_{table}', rejects_scan='rejscan_{table}')"
        )
        info["rejects"] = con.execute(f"SELECT count(*) FROM rej_{table}").fetchone()[0]
    # normalise filename column to the original basename
    mapping = {str(f["read_path"]): f["name"] for f in files}
    con.execute(f"ALTER TABLE {table} ADD COLUMN part VARCHAR")
    for rp, name in mapping.items():
        con.execute(f"UPDATE {table} SET part = ? WHERE filename = ?", [name, rp])
    con.execute(f"ALTER TABLE {table} DROP COLUMN filename")
    return info


def xlsx_value_to_str(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return v.isoformat(sep=" ")
    if isinstance(v, dt.date):
        return v.isoformat()
    return str(v)


def load_xlsx_dataset(con, ds: int, table: str, files: list[dict]) -> dict:
    info: dict = {"rejects": 0, "schema_same": True, "sniffed_types": {}, "headers": {}}
    frames = []
    cell_types: dict[str, set] = {}
    for fi in files:
        fi["encoding"], fi["delimiter"] = "—", "—"
        sheets = pd.read_excel(fi["path"], sheet_name=None, dtype=object, engine="openpyxl")
        fi["sheets"] = {name: len(df) for name, df in sheets.items()}
        for sheet, df in sheets.items():
            part = fi["name"] if len(sheets) == 1 else f"{fi['name']} [{sheet}]"
            info["headers"][part] = [str(c) for c in df.columns]
            for col in df.columns:
                types = {type(v).__name__ for v in df[col] if xlsx_value_to_str(v) is not None}
                cell_types.setdefault(str(col), set()).update(types)
            out = pd.DataFrame({str(c): [xlsx_value_to_str(v) for v in df[c]] for c in df.columns}, dtype=object)
            out["part"] = part
            frames.append(out)
    info["schema_same"] = len({tuple(h) for h in info["headers"].values()}) == 1
    if not info["schema_same"]:
        warn(ds, "XLSX sheets/files do NOT share one header")
    df_all = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    info["sniffed_types"] = {c: "xlsx: " + ("/".join(sorted(t)) or "empty") for c, t in cell_types.items()}
    con.register("xlsx_df", df_all)
    cols = ", ".join(f"CAST({q(c)} AS VARCHAR) AS {q(c)}" for c in df_all.columns)
    con.execute(f"CREATE TABLE {table} AS SELECT {cols} FROM xlsx_df")
    con.unregister("xlsx_df")
    return info


# ---------------------------------------------------------------- profiling
def profile_table(con, table: str, columns: list[str]) -> tuple[int, list[dict]]:
    total = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    pseudo = ", ".join(sql_str(p) for p in PSEUDO_NULLS)
    exprs = []
    for i, c in enumerate(columns):
        cc = q(c)
        exprs += [
            f"count({cc}) AS nn_{i}",
            f"count_if(lower(trim({cc})) IN ({pseudo})) AS pn_{i}",
            f"count(DISTINCT {cc}) AS nd_{i}",
            f"count_if({cc} <> trim({cc})) AS ut_{i}",
            # regex, not TRY_CAST: DuckDB rounds '1694.81' to BIGINT instead of failing
            f"count_if(regexp_matches(trim({cc}), '^[+-]?[0-9]+$')) AS bi_{i}",
            f"count_if(regexp_matches(trim({cc}), '^0[0-9]')) AS lz_{i}",
            f"count(TRY_CAST(trim({cc}) AS DOUBLE)) AS db_{i}",
            f"count({ts_expr(c)}) AS ts_{i}",
            f"min({ts_expr(c)}) AS tmin_{i}",
            f"max({ts_expr(c)}) AS tmax_{i}",
            f"max(length({cc})) AS ml_{i}",
        ]
    row = con.execute(f"SELECT {', '.join(exprs)} FROM {table}").fetchone()
    names = [d[0] for d in con.description]
    r = dict(zip(names, row))
    cols = []
    for i, c in enumerate(columns):
        p = {k: r[f"{k}_{i}"] for k in ("nn", "pn", "nd", "ut", "bi", "lz", "db", "ts", "tmin", "tmax", "ml")}
        for k in ("nn", "pn", "nd", "ut", "bi", "lz", "db", "ts"):
            p[k] = p[k] or 0  # count_if over an all-NULL column can come back as NULL
        p["name"] = c
        p["nulls"] = total - p["nn"]
        v = p["nn"] - p["pn"]  # real values
        p["values"] = v
        if v <= 0:
            t = "EMPTY"
        elif p["lz"] and p["db"] >= 0.9 * v:
            t = "VARCHAR (numeric code with leading zeros)"
        elif p["bi"] >= v:
            t = "BIGINT"
        elif p["db"] >= v:
            t = "DOUBLE"
        elif p["ts"] >= v:
            t = "TIMESTAMP"
        elif p["ts"] >= 0.9 * v:
            t = f"mostly TIMESTAMP ({pct(p['ts'], v)} parse)"
        elif p["bi"] >= 0.9 * v:
            t = f"mostly integer ({pct(p['bi'], v)})"
        else:
            t = "VARCHAR"
        p["type"] = t
        lname = c.lower()
        p["is_date"] = v > 0 and (bool(DATE_NAME_RE.search(lname)) or (p["ts"] >= 0.9 * v and "TIMESTAMP" in t))
        p["is_id"] = bool(ID_NAME_RE.search(lname)) or (
            lname.endswith("code") and v > 0 and p["nd"] / max(p["nn"], 1) > 0.9 and total > 100
        )
        p["is_cat"] = (
            not p["is_id"]
            and not p["is_date"]
            and bool(CAT_NAME_RE.search(lname))
            and not (lname.endswith("_name") and not re.search(r"region|org|clinic", lname))
        )
        cols.append(p)
    return total, cols


def main_date_column(cols: list[dict], total: int) -> str | None:
    for p in cols:
        if p["is_date"] and p["name"] != "sdu_load_date" and p["ts"] >= 0.5 * total:
            return p["name"]
    return None


# ------------------------------------------------------------ dataset section
def analyse_dataset(con, ds: int, folder: Path, tmpdir: Path) -> tuple[list[str], dict]:
    title = DATASET_TITLES.get(ds, folder.name)
    lines = [f"## Dataset {ds} — {title}", "", f"Folder: `data/raw/{folder.name}`" + ("  · core" if ds in CORE else "  · secondary"), ""]
    summary: dict = {"ds": ds, "title": title, "table": None}

    all_files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    total_size = sum(p.stat().st_size for p in all_files)
    summary["size"] = total_size
    summary["n_files"] = len(all_files)
    if not all_files:
        lines += ["**Folder is empty — skipped.**", ""]
        warn(ds, "folder is empty (no files) — skipped")
        summary["status"] = "empty folder"
        return lines, summary

    files = []
    for p in all_files:
        status, note = classify_file(p)
        m = PART_RE.search(p.stem)
        files.append({"path": p, "name": p.name, "ext": p.suffix.lower(), "size": p.stat().st_size,
                      "status": status, "note": note, "part_no": (int(m.group(1)), int(m.group(2))) if m else None})
    files.sort(key=lambda f: (f["part_no"] or (0, 0), f["name"]))

    for f in files:
        if f["status"] != "ok":
            warn(ds, f"`{f['name']}` — {f['note'] or f['status']}; excluded from profiling")
    declared = {f["part_no"][1] for f in files if f["part_no"]}
    if declared:
        n_decl = max(declared)
        present_ok = {f["part_no"][0] for f in files if f["part_no"] and f["status"] == "ok"}
        missing = sorted(set(range(1, n_decl + 1)) - present_ok)
        if missing:
            warn(ds, f"file names declare {n_decl} parts but usable parts are missing: {missing}")
            summary["missing_parts"] = missing

    usable = [f for f in files if f["status"] == "ok" and f["ext"] in (".csv", ".xlsx")]
    table = f"ds{ds}"
    info: dict = {}
    t0 = time.time()
    if usable:
        exts = {f["ext"] for f in usable}
        if exts == {".csv"}:
            info = load_csv_dataset(con, ds, table, usable, tmpdir)
        elif exts == {".xlsx"}:
            info = load_xlsx_dataset(con, ds, table, usable)
        else:
            warn(ds, f"mixed file types {sorted(exts)}; only CSV parts profiled")
            usable = [f for f in usable if f["ext"] == ".csv"]
            info = load_csv_dataset(con, ds, table, usable, tmpdir)

    # --- files table
    lines += ["### Files", ""]
    rows = []
    for f in files:
        rows.append([md_cell(f["name"], 90), f["ext"], fmt_size(f["size"]), f.get("encoding", "—"),
                     md_cell(f.get("delimiter", "—")).replace("\t", "TAB"),
                     "ok" if f["status"] == "ok" else f"**{f['status'].upper()}** — {f['note']}"])
    lines += md_table(["file", "ext", "size", "encoding", "delim", "status"], rows)
    lines += ["", f"Total folder size: **{fmt_size(total_size)}** in {len(files)} file(s); "
              f"usable: {len(usable)}.", ""]
    for f in usable:
        if f.get("sheets"):
            lines.append(f"- `{f['name']}` sheets: " + ", ".join(f"{k} ({fmt_int(v)} rows)" for k, v in f["sheets"].items()))
    if any(f.get("sheets") for f in usable):
        lines.append("")

    if not usable:
        lines += ["**No usable data files — skipped.**", ""]
        summary["status"] = "no usable files"
        return lines, summary

    summary["table"] = table
    columns = [c for c in con.execute(f"SELECT * FROM {table} LIMIT 0").fetchdf().columns if c != "part"]
    total, cols = profile_table(con, table, columns)
    summary.update(total=total, cols=cols, n_cols=len(columns), load_s=time.time() - t0, info=info)

    if info.get("rejects"):
        warn(ds, f"{fmt_int(info['rejects'])} malformed CSV rows were skipped")

    ref_row = None
    if "sdu_load_date" in columns:
        ref_row = con.execute(f"SELECT max({ts_expr('sdu_load_date')}) FROM {table}").fetchone()[0]
    ref_date = ref_row or dt.datetime.now()
    summary["ref_date"] = ref_date

    # --- schema
    lines += ["### Schema and column profile", "",
              f"Rows: **{fmt_int(total)}** · columns: **{len(columns)}**"
              + (f" · malformed rows skipped: **{fmt_int(info['rejects'])}**" if info.get("rejects") else ""), "",
              "`sniffed` = DuckDB/openpyxl guess; `full-scan type` = narrowest type every non-null value casts to. "
              "`pseudo-null` = literal strings like 'NaT', 'nan', 'NULL', '-'. "
              "`untrimmed` = values with leading/trailing whitespace.", ""]
    rows = []
    for i, p in enumerate(cols, 1):
        tags = [t for t, flag in (("date", p["is_date"]), ("id", p["is_id"]), ("cat", p["is_cat"])) if flag]
        rows.append([i, f"`{p['name']}`", info.get("sniffed_types", {}).get(p["name"], "?"), p["type"],
                     pct(p["nulls"], total), pct(p["pn"], total) if p["pn"] else "0", fmt_int(p["nd"]),
                     fmt_int(p["ut"]) if p["ut"] else "0", p["ml"] if p["ml"] is not None else "—", ", ".join(tags)])
        if p["values"] <= 0:
            warn(ds, f"column `{p['name']}` is completely empty")
        elif p["nulls"] + p["pn"] > 0.95 * total:
            warn(ds, f"column `{p['name']}` is {pct(p['nulls'] + p['pn'], total)} null/pseudo-null")
        if p["pn"]:
            sample_pn = con.execute(
                f"SELECT {q(p['name'])}, count(*) FROM {table} WHERE lower(trim({q(p['name'])})) IN "
                f"({', '.join(sql_str(x) for x in PSEUDO_NULLS)}) GROUP BY 1 ORDER BY 2 DESC LIMIT 3").fetchall()
            warn(ds, f"column `{p['name']}` has {fmt_int(p['pn'])} pseudo-null strings "
                     + ", ".join(f"'{v}'×{fmt_int(n)}" for v, n in sample_pn))
        if p["ut"] and p["ut"] > 0.001 * total:
            warn(ds, f"column `{p['name']}` has {fmt_int(p['ut'])} values with leading/trailing whitespace")
        if "leading zeros" in p["type"]:
            warn(ds, f"column `{p['name']}` is a code with leading zeros — must stay VARCHAR")
        sniffed = info.get("sniffed_types", {}).get(p["name"], "")
        if "leading zeros" in p["type"] and sniffed in ("BIGINT", "INTEGER"):
            warn(ds, f"DuckDB's default sniffer types `{p['name']}` as {sniffed} → would drop leading zeros")
    lines += md_table(["#", "column", "sniffed", "full-scan type", "null %", "pseudo-null %", "distinct",
                       "untrimmed", "max len", "tags"], rows)
    lines.append("")

    # --- dates
    date_cols = [p for p in cols if p["is_date"]]
    summary["date_cols"] = date_cols
    if date_cols:
        lines += ["### Date-like columns", "",
                  f"Reference 'now' for impossible-future check: max `sdu_load_date` = {ref_date}.", ""]
        exprs = []
        for i, p in enumerate(date_cols):
            e = ts_expr(p["name"])
            exprs += [f"count_if({e} < TIMESTAMP '{MIN_PLAUSIBLE_DATE}') AS old_{i}",
                      f"count_if({e} > TIMESTAMP '{ref_date}') AS fut_{i}",
                      f"count_if({e} IS NOT NULL AND {e} = date_trunc('day', {e})) AS mid_{i}"]
        r = dict(zip([f"{k}_{i}" for i in range(len(date_cols)) for k in ("old", "fut", "mid")],
                     con.execute(f"SELECT {', '.join(exprs)} FROM {table}").fetchone()))
        rows = []
        for i, p in enumerate(date_cols):
            unparsed = p["values"] - p["ts"]
            p["old"], p["fut"] = r[f"old_{i}"], r[f"fut_{i}"]
            rows.append([f"`{p['name']}`", p["tmin"], p["tmax"], fmt_int(p["ts"]), fmt_int(unparsed),
                         fmt_int(p["old"]), fmt_int(p["fut"]), pct(r[f"mid_{i}"], p["ts"])])
            if unparsed > 0:
                warn(ds, f"`{p['name']}`: {fmt_int(unparsed)} non-null values do not parse as dates")
            if p["old"]:
                warn(ds, f"`{p['name']}`: {fmt_int(p['old'])} dates before {MIN_PLAUSIBLE_DATE}")
            if p["fut"] and p["name"] != "sdu_load_date":
                warn(ds, f"`{p['name']}`: {fmt_int(p['fut'])} dates after the data load date ({ref_date:%Y-%m-%d})")
        lines += md_table(["column", "min", "max", "parsed", "unparsed", f"< {MIN_PLAUSIBLE_DATE}",
                           "> load date", "time = 00:00"], rows)
        lines.append("")

    # --- categorical
    cat_cols = [p for p in cols if p["is_cat"]]
    if cat_cols:
        lines += ["### Categorical columns (region / organization / status / profile / diagnosis …)", ""]
        rows = []
        for p in cat_cols:
            # a Latin letter glued to a Cyrillic one inside a word, e.g. 'Oбласть' with Latin O
            mixed = con.execute(
                f"SELECT count(DISTINCT {q(p['name'])}), arg_min({q(p['name'])}, length({q(p['name'])})) FROM {table} "
                f"WHERE regexp_matches({q(p['name'])}, '[A-Za-z][А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі]|[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүҺһІі][A-Za-z]')"
            ).fetchone()
            if mixed[0]:
                warn(ds, f"`{p['name']}`: {fmt_int(mixed[0])} distinct values mix Latin and Cyrillic letters inside a word "
                         f"(e.g. '{md_cell(mixed[1], 50)}') — exact-name joins will miss them")
            top = con.execute(f"SELECT {q(p['name'])}, count(*) n FROM {table} GROUP BY 1 ORDER BY n DESC LIMIT 5").fetchall()
            top_s = "; ".join(f"{md_cell(v, 45)} ({pct(n, total)})" for v, n in top)
            rows.append([f"`{p['name']}`", fmt_int(p["nd"]), top_s])
        lines += md_table(["column", "distinct", "top-5 values (share of rows)"], rows)
        lines.append("")

    # --- ids
    id_cols = [p for p in cols if p["is_id"]]
    lines += ["### ID-like columns and uniqueness", ""]
    if id_cols:
        rows = []
        for p in id_cols:
            dups = p["nn"] - p["nd"]
            unique = p["nulls"] == 0 and dups == 0
            rows.append([f"`{p['name']}`", fmt_int(p["nn"]), fmt_int(p["nulls"]), fmt_int(p["nd"]), fmt_int(dups),
                         "**yes**" if unique else "no"])
            if not unique and p["values"] > 0:
                warn(ds, f"id-like `{p['name']}` is not unique: {fmt_int(dups)} repeated values, {fmt_int(p['nulls'])} nulls")
        lines += md_table(["column", "non-null", "null", "distinct", "repeated values", "unique?"], rows)
    else:
        lines.append("No id-like column found.")
        warn(ds, "no id-like column — rows cannot be uniquely identified")
    lines.append("")

    # --- full-row duplicates
    hash_cols = ", ".join(q(c) for c in columns)
    dup = con.execute(f"SELECT count(*) - count(DISTINCT hash({hash_cols})) FROM {table}").fetchone()[0]
    summary["dup_rows"] = dup
    lines += ["### Duplicates", "", f"Exact duplicate rows (all columns identical): **{fmt_int(dup)}** ({pct(dup, total)})."]
    if dup:
        warn(ds, f"{fmt_int(dup)} exact duplicate rows ({pct(dup, total)})")
    lines.append("")

    # --- parts
    parts = con.execute(f"SELECT DISTINCT part FROM {table}").fetchall()
    if len(parts) > 1:
        lines += analyse_parts(con, ds, table, columns, cols, total, info, summary)

    # --- dataset-specific logical checks
    checks = logical_checks(con, ds, table, columns, total)
    if checks:
        lines += ["### Logical consistency checks", ""]
        lines += md_table(["check", "rows", "share"], [[c, fmt_int(n), pct(n, total)] for c, n in checks])
        lines.append("")

    # --- samples
    lines += ["### Sample rows (first 5)", ""]
    sample = con.execute(f"SELECT {hash_cols} FROM {table} LIMIT 5").fetchall()
    rows = [[f"`{c}`"] + [md_cell(r[j], 40) for r in sample] for j, c in enumerate(columns)]
    lines += md_table(["column"] + [f"row {i + 1}" for i in range(len(sample))], rows)
    lines.append("")
    summary["status"] = "ok"
    return lines, summary


def analyse_parts(con, ds, table, columns, cols, total, info, summary) -> list[str]:
    lines = ["### Multi-part layout", ""]
    if info.get("schema_same"):
        lines.append(f"All {len(info['headers'])} parts share **one identical header** ({len(columns)} columns).")
    else:
        lines.append("**Parts have different headers:**")
        for name, h in info["headers"].items():
            lines.append(f"- `{name}`: {', '.join(h)}")
    lines.append("")

    mdc = main_date_column(cols, total)
    date_cols = [p["name"] for p in cols if p["is_date"] and p["name"] != "sdu_load_date"]
    exprs = ["count(*) AS n"]
    for c in date_cols:
        exprs += [f"min({ts_expr(c)})::DATE", f"max({ts_expr(c)})::DATE"]
    res = con.execute(f"SELECT part, {', '.join(exprs)} FROM {table} GROUP BY part ORDER BY part").fetchall()
    header = ["part", "rows"] + [f"{c} {k}" for c in date_cols for k in ("min", "max")]
    lines += md_table(header, [[md_cell(r[0], 70), fmt_int(r[1])] + [str(x) for x in r[2:]] for r in res])
    lines.append("")

    verdict = []
    counts = [r[1] for r in res]
    if len(set(counts[:-1])) == 1:
        same = "all parts" if counts[-1] == counts[0] else "all parts except the last"
        verdict.append(f"{same} have exactly {fmt_int(counts[0])} rows → a fixed-row-count chunking of one export")
    if mdc:
        e = ts_expr(mdc)
        # month × part crosstab of the main event date
        ct = con.execute(
            f"SELECT strftime(date_trunc('month', {e}), '%Y-%m') m, part, count(*) FROM {table} "
            f"WHERE {e} IS NOT NULL GROUP BY ALL ORDER BY m").fetchall()
        part_names = sorted({r[1] for r in ct})
        grid: dict[str, dict[str, int]] = {}
        for m, part, n in ct:
            grid.setdefault(m, {})[part] = n
        lines += [f"Rows per month of `{mdc}` by part:", ""]
        short = [f"part {i + 1}" if not PART_RE.search(p) else f"part {PART_RE.search(p).group(1)}" for i, p in enumerate(part_names)]
        lines += md_table(["month"] + short, [[m] + [fmt_int(grid[m].get(p, 0)) for p in part_names] for m in sorted(grid)])
        lines.append("")
        # overlap of part time ranges (5th–95th percentile to ignore outliers)
        rng = con.execute(
            f"SELECT part, quantile_cont(epoch({e}), 0.05), quantile_cont(epoch({e}), 0.95) FROM {table} "
            f"WHERE {e} IS NOT NULL GROUP BY part ORDER BY 2").fetchall()
        overlaps = sum(1 for a, b in zip(rng, rng[1:]) if b[1] < a[2])
        if overlaps == 0:
            verdict.append(f"by `{mdc}`: 5–95% time ranges of parts do not overlap → looks **split by time**")
        else:
            verdict.append(f"by `{mdc}`: {overlaps} of {len(rng) - 1} adjacent parts overlap in time → **not a clean time split**")

    # are categorical values (e.g. region) disjoint across parts?
    for p in cols:
        if p["is_cat"] and p["nd"] <= 5000:
            shared, nvals = con.execute(
                f"SELECT count_if(np > 1), count(*) FROM (SELECT {q(p['name'])}, count(DISTINCT part) np FROM {table} "
                f"WHERE {q(p['name'])} IS NOT NULL GROUP BY 1)").fetchone()
            if nvals and shared == 0:
                verdict.append(f"every value of `{p['name']}` ({fmt_int(nvals)} distinct) occurs in exactly one part → "
                               f"parts look **split by `{p['name']}`**")
            elif nvals and re.search(r"region", p["name"]):
                verdict.append(f"`{p['name']}`: {fmt_int(shared)} of {fmt_int(nvals)} values occur in more than one part")

    # ids / rows repeated across parts
    for p in cols:
        if p["is_id"] and p["values"] > 0:
            n = con.execute(f"SELECT count(*) FROM (SELECT {q(p['name'])} FROM {table} WHERE {q(p['name'])} IS NOT NULL "
                            f"GROUP BY 1 HAVING count(DISTINCT part) > 1)").fetchone()[0]
            verdict.append(f"`{p['name']}` values present in more than one part: {fmt_int(n)}")
            if n:
                warn(ds, f"{fmt_int(n)} `{p['name']}` values appear in more than one part")
    hash_cols = ", ".join(q(c) for c in columns)
    n = con.execute(f"SELECT count(*) FROM (SELECT hash({hash_cols}) h FROM {table} GROUP BY h HAVING count(DISTINCT part) > 1)").fetchone()[0]
    verdict.append(f"identical rows present in more than one part: {fmt_int(n)}")
    if n:
        warn(ds, f"{fmt_int(n)} identical rows appear in more than one part (overlapping parts)")
    summary["parts_verdict"] = verdict
    lines += ["**How the parts are split:**", ""] + [f"- {v}" for v in verdict] + [""]
    return lines


def logical_checks(con, ds, table, columns, total) -> list[tuple[str, int]]:
    cs = set(columns)
    out: list[tuple[str, int]] = []

    def cnt(where: str) -> int:
        return con.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]

    T = ts_expr
    if {"hospitalization_dt", "refusal_dt"} <= cs:
        h, r = f"{T('hospitalization_dt')} IS NOT NULL", f"{T('refusal_dt')} IS NOT NULL"
        out += [("outcome: hospitalized only (hospitalization_dt set, refusal_dt empty)", cnt(f"{h} AND NOT ({r})")),
                ("outcome: refused only (refusal_dt set, hospitalization_dt empty)", cnt(f"{r} AND NOT ({h})")),
                ("outcome: BOTH hospitalization_dt and refusal_dt set", cnt(f"{h} AND {r}")),
                ("outcome: neither set (still open / unknown)", cnt(f"NOT ({h}) AND NOT ({r})"))]
    if {"registration_dt", "hospitalization_dt"} <= cs:
        h, r = T("hospitalization_dt"), T("registration_dt")
        out += [("hospitalization_dt earlier than registration_dt by < 1 day (referral registered after admission)",
                 cnt(f"{h} < {r} AND {r} - {h} < INTERVAL 1 DAY")),
                ("hospitalization_dt earlier than registration_dt by ≥ 1 day", cnt(f"{r} - {h} >= INTERVAL 1 DAY"))]
    if {"registration_dt", "refusal_dt"} <= cs:
        out.append(("refusal_dt earlier than registration_dt", cnt(f"{T('refusal_dt')} < {T('registration_dt')}")))
    if {"registration_dt", "planned_dt"} <= cs:
        out.append(("planned_dt (date) earlier than registration_dt (date)",
                    cnt(f"{T('planned_dt')}::DATE < {T('registration_dt')}::DATE")))
    if {"registration_dt", "polyclinic_dt"} <= cs:
        out.append(("polyclinic_dt earlier than registration_dt", cnt(f"{T('polyclinic_dt')} < {T('registration_dt')}")))
    if {"planned_dt", "sdu_load_date"} <= cs and "hospitalization_dt" not in cs:
        out.append(("planned_dt already in the past at load date (overdue waiting)",
                    cnt(f"{T('planned_dt')} < {T('sdu_load_date')}")))
    if {"hospitalization_code"} <= cs:
        out.append(("hospitalization_code does not have 4 dot-separated parts",
                    cnt("len(string_split(hospitalization_code, '.')) <> 4")))
    key = ["region_origin_code", "mo_destination_code", "profile_code", "patient_seq_no"]
    if set(key) <= cs:
        kc = ", ".join(key)
        n = con.execute(f"SELECT count(*) - count(DISTINCT ({kc})) FROM {table}").fetchone()[0]
        out.append((f"rows with repeated composite key ({kc})", n))
    if {"discharged_total", "discharged_children"} <= cs:
        out.append(("discharged_children > discharged_total",
                    cnt("TRY_CAST(discharged_children AS DOUBLE) > TRY_CAST(discharged_total AS DOUBLE)")))
    if {"discharged_total", "deaths_total"} <= cs:
        out.append(("deaths_total > discharged_total",
                    cnt("TRY_CAST(deaths_total AS DOUBLE) > TRY_CAST(discharged_total AS DOUBLE)")))
    if {"discharged_total", "treated_budget", "treated_paid"} <= cs:
        out.append(("treated_budget + treated_paid ≠ discharged_total (column semantics unclear — informational)",
                    cnt("TRY_CAST(treated_budget AS DOUBLE) + TRY_CAST(treated_paid AS DOUBLE) <> TRY_CAST(discharged_total AS DOUBLE)")))
    if {"take_in_date", "diagnosis_date"} <= cs:
        out.append(("diagnosis_date later than take_in_date", cnt(f"{T('diagnosis_date')}::DATE > {T('take_in_date')}::DATE")))
    if "age" in cs:
        out.append(("age outside 0–120", cnt("TRY_CAST(age AS DOUBLE) < 0 OR TRY_CAST(age AS DOUBLE) > 120")))
    if {"total_patients", "advanced_stage_3_count", "advanced_stage_4_count"} <= cs:
        out.append(("stage 3 + stage 4 counts > total_patients",
                    cnt("TRY_CAST(advanced_stage_3_count AS DOUBLE) + TRY_CAST(advanced_stage_4_count AS DOUBLE) > TRY_CAST(total_patients AS DOUBLE)")))
    for c, n in out:
        if n and not c.startswith(("outcome:", "planned_dt already", "treated_budget")):
            warn(ds, f"logical check — {c}: {fmt_int(n)} rows ({pct(n, total)})")
    return out


# ------------------------------------------------------------- join section
NORM_ORG = ("lower(regexp_replace(regexp_replace(trim({x}), '[\"«»“”''`]', '', 'g'), '\\s+', ' ', 'g'))")


def join_section(con, summaries: dict[int, dict]) -> list[str]:
    L = ["## Join keys and observations", ""]
    tables = {ds: s["table"] for ds, s in summaries.items() if s.get("table")}

    def has(ds, *cols):
        s = summaries.get(ds)
        return bool(s and s.get("table")) and set(cols) <= {p["name"] for p in s["cols"]}

    def one(sql):
        return con.execute(sql).fetchone()

    # 1. referral code ↔ waiting-list key
    L += ["### 1. Candidate join keys (checked against the data)", ""]
    if has(1, "hospitalization_code", "hospital_mo", "referring_mo"):
        t1 = tables[1]
        L += ["**Dataset 1 `hospitalization_code` structure** (e.g. `33.22HJ.DH.52`):", ""]
        nparts = con.execute(f"SELECT len(string_split(hospitalization_code, '.')) k, count(*) FROM {t1} GROUP BY 1 ORDER BY 2 DESC").fetchall()
        L.append("- dot-separated parts: " + ", ".join(f"{k} parts → {fmt_int(n)} rows" for k, n in nparts))
        d = one(f"SELECT count(DISTINCT split_part(hospitalization_code,'.',1)), count(DISTINCT split_part(hospitalization_code,'.',2)), "
                f"count(DISTINCT split_part(hospitalization_code,'.',3)) FROM {t1}")
        L.append(f"- distinct values of part 1: {fmt_int(d[0])} (looks like a 2-digit region code), "
                 f"part 2: {fmt_int(d[1])} (4-char organization code), part 3: {fmt_int(d[2])} (bed-profile code), part 4: sequence number")
        mo = one(f"SELECT avg(nh), avg(nr), count_if(nh = 1)::DOUBLE / count(*), count_if(nr = 1)::DOUBLE / count(*) FROM ("
                 f"SELECT split_part(hospitalization_code,'.',2) k, count(DISTINCT hospital_mo) nh, count(DISTINCT referring_mo) nr "
                 f"FROM {t1} GROUP BY 1)")
        L.append(f"- per part-2 code: avg distinct `hospital_mo` names = {mo[0]:.2f} ({100*mo[2]:.0f}% of codes map to exactly one), "
                 f"avg distinct `referring_mo` names = {mo[1]:.2f} ({100*mo[3]:.0f}% map to one) → part 2 encodes the "
                 f"**{'hospital (destination)' if mo[2] > mo[3] else 'referring'} organization**, "
                 f"so the code gives a name↔code dictionary for organizations")
        L.append("")
        if has(2, "region_origin_code", "mo_destination_code", "profile_code", "patient_seq_no"):
            t2 = tables[2]
            key2 = "region_origin_code || '.' || mo_destination_code || '.' || profile_code || '.' || patient_seq_no"
            m = one(f"SELECT count(*), count_if(k IN (SELECT hospitalization_code FROM {t1})) FROM (SELECT {key2} k FROM {t2})")
            L += ["**Dataset 2 ↔ dataset 1 via `region_origin_code.mo_destination_code.profile_code.patient_seq_no` = `hospitalization_code`:**", "",
                  f"- dataset 2 rows whose composite key exists in dataset 1: **{fmt_int(m[1])} of {fmt_int(m[0])}** ({pct(m[1], m[0])})"]
            for label, e1, e2 in (("region code", "split_part(hospitalization_code,'.',1)", "region_origin_code"),
                                  ("organization code", "split_part(hospitalization_code,'.',2)", "mo_destination_code"),
                                  ("profile code", "split_part(hospitalization_code,'.',3)", "profile_code")):
                a = one(f"SELECT (SELECT count(DISTINCT {e2}) FROM {t2}), count(*) FROM (SELECT DISTINCT {e2} v FROM {t2} "
                        f"INTERSECT SELECT DISTINCT {e1} FROM {t1})")
                L.append(f"- {label}: {fmt_int(a[1])} of {fmt_int(a[0])} distinct dataset-2 values also occur in dataset 1 codes")
            back = one(f"SELECT count(*), count_if(hospitalization_code IN (SELECT {key2} FROM {t2})) FROM {t1}")
            L.append(f"- dataset 1 rows whose code exists in dataset 2: **{fmt_int(back[1])} of {fmt_int(back[0])}** ({pct(back[1], back[0])})")
            if has(1, "hospitalization_dt", "refusal_dt"):
                oc = con.execute(
                    f"SELECT CASE WHEN {ts_expr('hospitalization_dt')} IS NOT NULL THEN 'already hospitalized' "
                    f"WHEN {ts_expr('refusal_dt')} IS NOT NULL THEN 'refused' ELSE 'no outcome yet' END o, count(*) "
                    f"FROM {t1} WHERE hospitalization_code IN (SELECT {key2} FROM {t2}) GROUP BY 1 ORDER BY 2 DESC").fetchall()
                matched = sum(n for _, n in oc)
                L.append("- dataset 1 outcome of the referrals that appear in dataset 2: "
                         + "; ".join(f"{o} {fmt_int(n)} ({pct(n, matched)})" for o, n in oc))
                open_share = sum(n for o, n in oc if o == "no outcome yet") / max(matched, 1)
                if back[1] > 0.9 * back[0] and open_share < 0.5:
                    L.append("- ⇒ dataset 2 holds (almost) the **same referral cohort as dataset 1**, including referrals that were "
                             "already hospitalized or refused — it is **not a current waiting-list snapshot** despite its title")
                    warn(2, "is essentially the same referral set as dataset 1 (same keys, same registration window, mostly already "
                            "hospitalized/refused) — not a 'currently waiting' snapshot; do not add it to dataset 1 as extra volume")
            L.append("")
        if has(1, "bed_profile"):
            pr = one(f"SELECT count(*), count_if(n = 1), count_if(n = 0) FROM (SELECT split_part(hospitalization_code,'.',3) p, "
                     f"count(DISTINCT trim(bed_profile)) n FROM {t1} GROUP BY 1)")
            dh = one(f"SELECT count_if(split_part(hospitalization_code,'.',3) = 'DH'), "
                     f"count_if(split_part(hospitalization_code,'.',3) = 'DH' AND bed_profile IS NULL), "
                     f"count_if(bed_profile IS NULL) FROM {t1}")
            L += ["**Profile code (code part 3 / ds2 `profile_code`) ↔ ds1 `bed_profile` name:**", "",
                  f"- {fmt_int(pr[1])} of {fmt_int(pr[0])} profile codes map to exactly one `bed_profile` name; "
                  f"{fmt_int(pr[2])} code(s) have no name at all → a code→name dictionary can be built from dataset 1",
                  f"- code `DH`: {fmt_int(dh[0])} rows, of which {fmt_int(dh[1])} have empty `bed_profile` "
                  f"(all empty `bed_profile` rows: {fmt_int(dh[2])}) → `DH` is probably the day hospital (дневной стационар), "
                  f"which has no bed profile", ""]
            top = con.execute(f"SELECT split_part(hospitalization_code,'.',3) p, any_value(trim(bed_profile)) n, count(*) c "
                              f"FROM {t1} GROUP BY 1 ORDER BY c DESC LIMIT 12").fetchall()
            L += md_table(["profile code", "bed_profile", "rows"], [[p, md_cell(n, 60), fmt_int(c)] for p, n, c in top])
            L += ["", "(top 12 by rows)", ""]
        # region prefix → typical hospital
        L += ["**Dataset 1 region prefix → most frequent `hospital_mo`** (to confirm/decode region codes):", ""]
        reg = con.execute(
            f"WITH x AS (SELECT split_part(hospitalization_code,'.',1) r, hospital_mo, count(*) n FROM {t1} GROUP BY 1, 2), "
            f"t AS (SELECT r, sum(n) total, arg_max(hospital_mo, n) top FROM x GROUP BY r) SELECT r, total, top FROM t ORDER BY r").fetchall()
        L += md_table(["prefix", "rows", "most frequent hospital_mo"], [[r, fmt_int(n), md_cell(top, 110)] for r, n, top in reg[:40]])
        if len(reg) > 40:
            L.append(f"\n… {len(reg) - 40} more prefixes")
        L.append("")

    # organization names
    org_sources = [(1, "hospital_mo"), (1, "referring_mo"), (3, "org_in"), (3, "attach_org"), (4, "medicine_organization"), (7, "clinic_name")]
    org_sources = [(ds, c) for ds, c in org_sources if has(ds, c)]
    if len(org_sources) > 1:
        L += ["**Organization names (no BIN/organization code in datasets 1, 3, 4 — only full names).** "
              "Overlap of distinct names after normalisation (lower-case, quotes removed, whitespace collapsed):", ""]
        sets = {}
        for ds, c in org_sources:
            name = f"org_{ds}_{c}"
            con.execute(f"CREATE OR REPLACE TEMP TABLE {name} AS SELECT DISTINCT {NORM_ORG.format(x=q(c))} v FROM {tables[ds]} WHERE {q(c)} IS NOT NULL")
            sets[(ds, c)] = name
        rows = []
        pairs = [((1, "hospital_mo"), (3, "org_in")), ((1, "hospital_mo"), (4, "medicine_organization")),
                 ((3, "org_in"), (4, "medicine_organization")), ((1, "referring_mo"), (3, "attach_org")),
                 ((1, "hospital_mo"), (7, "clinic_name"))]
        for a, b in pairs:
            if a in sets and b in sets:
                na, nb, ni = one(f"SELECT (SELECT count(*) FROM {sets[a]}), (SELECT count(*) FROM {sets[b]}), "
                                 f"(SELECT count(*) FROM (SELECT v FROM {sets[a]} INTERSECT SELECT v FROM {sets[b]}))")
                raw = one(f"SELECT count(*) FROM (SELECT DISTINCT {q(a[1])} FROM {tables[a[0]]} INTERSECT SELECT DISTINCT {q(b[1])} FROM {tables[b[0]]})")[0]
                rows.append([f"ds{a[0]}.`{a[1]}`", fmt_int(na), f"ds{b[0]}.`{b[1]}`", fmt_int(nb), fmt_int(raw), f"{fmt_int(ni)} ({pct(ni, nb)} of right side)"])
        L += md_table(["left", "distinct", "right", "distinct", "exact-match names", "normalised matches"], rows)
        L.append("")
        if has(4, "medicine_organization"):
            raw_n, norm_n = one(f"SELECT count(DISTINCT medicine_organization), count(DISTINCT {NORM_ORG.format(x='medicine_organization')}) FROM {tables[4]}")
            if norm_n < raw_n:
                L += [f"- dataset 4: {fmt_int(raw_n)} distinct raw names collapse to {fmt_int(norm_n)} after normalisation → "
                      f"{fmt_int(raw_n - norm_n)} organizations appear more than once under slightly different spellings", ""]
                warn(4, f"{fmt_int(raw_n - norm_n)} organization names are duplicates up to quotes/case/spacing "
                        f"(rows are supposed to be one per organization)")

    # region names (to build the code ↔ name dictionary)
    if has(3, "region_in"):
        L += ["**Region names in dataset 3** (all values; the numeric codes in ds1/ds2 look like KATO region codes — "
              "compare with the prefix table above):", ""]
        reg = con.execute(f"SELECT region_in, count(*) FROM {tables[3]} GROUP BY 1 ORDER BY 1").fetchall()
        att = dict(con.execute(f"SELECT attach_region, count(*) FROM {tables[3]} GROUP BY 1").fetchall()) if has(3, "attach_region") else {}
        names = sorted({r for r, _ in reg} | {a for a in att if a is not None}, key=lambda x: (x is None, x or ""))
        regd = dict(reg)
        L += md_table(["region name", "rows as `region_in`", "rows as `attach_region`"],
                      [[md_cell(n), fmt_int(regd.get(n, 0)), fmt_int(att.get(n, 0))] for n in names])
        L.append("")
        absent = [n for n in names if n is not None and regd.get(n, 0) == 0 and att.get(n, 0) > 1000]
        if absent and summaries[3].get("missing_parts"):
            L += [f"- regions present as `attach_region` but with **0 rows as `region_in`**: {', '.join(absent)} — "
                  f"since parts {summaries[3]['missing_parts']} are missing and the export looks ordered by region "
                  f"(see sample rows), these regions' hospitals are probably in the missing parts", ""]
            warn(3, f"no refusals at all for hospitals in {', '.join(absent)} — probably inside the missing parts, "
                    f"so regional comparisons on dataset 3 are biased until parts are re-downloaded")

    # volume sanity: ds3 refusals vs ds1 refusals
    if has(1, "refusal_dt") and has(3, "refuse_dt"):
        n1 = one(f"SELECT count({ts_expr('refusal_dt')}) FROM {tables[1]}")[0]
        n1q = one(f"SELECT count_if({ts_expr('refusal_dt')} BETWEEN (SELECT min({ts_expr('refuse_dt')}) FROM {tables[3]}) "
                  f"AND (SELECT max({ts_expr('refuse_dt')}) FROM {tables[3]})) FROM {tables[1]}")[0]
        n3 = summaries[3]["total"]
        L += ["**Refusal volume check:**", "",
              f"- dataset 1 referrals with `refusal_dt`: {fmt_int(n1)} (of which {fmt_int(n1q)} inside dataset 3's `refuse_dt` window)",
              f"- dataset 3 rows (only {len(summaries[3]['info'].get('headers', {}))} usable parts): {fmt_int(n3)} — "
              f"{n3 / max(n1q, 1):.1f}× more than ds1 refusals in the same window", ""]
        if n3 > 3 * max(n1q, 1):
            L += ["- ⇒ dataset 3 is far larger than the planned-referral refusals of dataset 1; together with its diagnoses "
                  "(see top `icd10` values) it likely covers **all admission-unit refusals** (not only planned referrals) — "
                  "treat it as a separate flow, not as the refusal outcome of dataset 1 referrals", ""]
            warn(3, f"{n3 / max(n1q, 1):.1f}× more rows than dataset 1 refusals in the same window, even with 2 of 6 parts "
                    f"missing — likely not limited to planned referrals")

    # ICD codes
    icd_sources = [(1, "icd10_ref_diag_code"), (2, "icd10_ref_diag_code"), (3, "icd10"), (7, "diagnosis_code")]
    icd_sources = [(ds, c) for ds, c in icd_sources if has(ds, c)]
    if len(icd_sources) > 1:
        L += ["**ICD-10 diagnosis codes** (after trim/upper-case) — shared with dataset 1:", ""]
        rows = []
        for ds, c in icd_sources:
            nd, ni = one(f"WITH a AS (SELECT DISTINCT upper(trim({q(c)})) v FROM {tables[ds]} WHERE {q(c)} IS NOT NULL) "
                         f"SELECT (SELECT count(*) FROM a), (SELECT count(*) FROM a WHERE v IN "
                         f"(SELECT upper(trim(icd10_ref_diag_code)) FROM {tables[1]}))") if 1 in tables else (None, None)
            rows.append([f"ds{ds}.`{c}`", fmt_int(nd), fmt_int(ni)])
        L += md_table(["column", "distinct codes", "also in ds1"], rows)
        L.append("")

    L += ["**Summary of link candidates**", "",
          "| link | key | quality |", "|---|---|---|",
          "| 1 ↔ 2 | `hospitalization_code` = `region_origin_code.mo_destination_code.profile_code.patient_seq_no` | see match rate above; strongest candidate (row level) |",
          "| 1 ↔ 3 | no shared id; `hospital_mo` ↔ `org_in` (names), `icd10_ref_diag_code` ↔ `icd10`, `refusal_dt` ↔ `refuse_dt`, `finance_source` ↔ `finance_src` | fuzzy / aggregate level only |",
          "| 1 ↔ 4 | `hospital_mo` ↔ `medicine_organization` (names only, no BIN, no dates) | organization level only |",
          "| 3 ↔ 4 | `org_in` ↔ `medicine_organization` (names) | organization level only |",
          "| region | ds1 code prefix / ds2 `region_origin_code` (numeric) vs ds3 `region_in`, `attach_region` (names) | needs a region code ↔ name dictionary |",
          "| dates | ds1 `registration_dt`/`planned_dt`/`hospitalization_dt`/`refusal_dt`, ds2 `registration_dt`/`planned_dt`, ds3 `refuse_dt`; ds4 has none (snapshot) | calendar alignment only |",
          ""]

    # 2. time coverage
    L += ["### 2. Time coverage", ""]
    rows = []
    for ds, s in sorted(summaries.items()):
        if not s.get("table"):
            rows.append([ds, s["title"], "—", "—", "—", s.get("status", "")])
            continue
        mdc = main_date_column(s["cols"], s["total"])
        p = next((c for c in s["cols"] if c["name"] == mdc), None)
        other = [f"`{c['name']}` {str(c['tmin'])[:10]} → {str(c['tmax'])[:10]}" for c in s["date_cols"]
                 if c["name"] not in (mdc, "sdu_load_date")]
        rows.append([ds, s["title"], f"`{mdc}`" if mdc else "no event date (snapshot)",
                     f"{str(p['tmin'])[:10]} → {str(p['tmax'])[:10]}" if p else "—",
                     str(s.get("ref_date"))[:19] if any(c["name"] == "sdu_load_date" for c in s["cols"]) else "—",
                     "; ".join(other)])
    L += md_table(["ds", "dataset", "main date column", "range", "sdu_load_date", "other date columns"], rows)
    L.append("")
    core_ranges = []
    for ds in sorted(CORE):
        s = summaries.get(ds, {})
        if s.get("table") and (mdc := main_date_column(s["cols"], s["total"])):
            p = next(c for c in s["cols"] if c["name"] == mdc)
            core_ranges.append((ds, p["tmin"], p["tmax"]))
    if core_ranges:
        lo, hi = min(r[1] for r in core_ranges), max(r[2] for r in core_ranges)
        months = (hi.year - lo.year) * 12 + hi.month - lo.month + 1
        L += [f"- Core event data (datasets {', '.join(str(r[0]) for r in core_ranges)}) covers **{months} calendar month(s)**: "
              f"{lo:%Y-%m-%d} → {hi:%Y-%m-%d}. Outcome dates (hospitalization/refusal) run until the load date, "
              "so the cohort is observed with a long follow-up. Dataset 4 has no dates (one period, unknown).", ""]
        if months < 12:
            warn(0, f"core event data covers only {months} months ({lo:%Y-%m} → {hi:%Y-%m}) — no seasonality/yearly pattern "
                    f"can be learned from it")

    # 3. suspicious
    L += ["### 3. Suspicious / needs attention (auto-detected)", ""]
    if not warnings_global:
        L += ["- nothing detected", ""]
    for level, label in (("critical", "Critical — affects what the data can be used for"),
                         ("notable", "Notable — data quality to handle during cleaning"),
                         ("minor", "Minor — formatting")):
        items = [w for w in warnings_global if severity(w) == level]
        if items:
            L += [f"**{label}**", ""] + [f"- {w}" for w in items] + [""]

    # 4. dictionaries
    L += ["### 4. Codes that need a dictionary", ""]
    dict_rows = []
    for ds, s in sorted(summaries.items()):
        if not s.get("table"):
            continue
        name_cols = [p for p in s["cols"] if p["name"].endswith("_name")]
        for p in s["cols"]:
            n = p["name"]
            if p["values"] <= 0 or p["is_date"] or n == "hospitalization_code" or re.search(r"icd|diag", n):
                continue
            looks_code = bool(re.search(r"(_code$|_id$)", n)) and (p["ml"] or 0) <= 12
            # a *_name column with a similar number of distinct values is treated as its decoding
            paired = any(abs(o["nd"] - p["nd"]) <= 0.2 * max(p["nd"], 1) for o in name_cols)
            if looks_code and not paired:
                why = "short code with no matching *_name column in the dataset"
                if ds == 2 and has(1, "hospitalization_code") and n == "mo_destination_code":
                    why += " — names recoverable from ds1 `hospital_mo` via `hospitalization_code` part 2"
                elif ds == 2 and has(1, "bed_profile") and n == "profile_code":
                    why += " — names recoverable from ds1 `bed_profile` via `hospitalization_code` part 3"
                elif n.startswith("region"):
                    why += " — looks like KATO region codes; no name source in ds1/ds2"
                dict_rows.append([ds, f"`{n}`", fmt_int(p["nd"]), why])
            elif (p["ml"] or 0) == 36:
                uuid = con.execute(f"SELECT count_if(regexp_matches({q(n)}, '^[0-9a-fA-F]{{8}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-"
                                   f"[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{12}}$')) FROM {s['table']}").fetchone()[0]
                if uuid > 0.5 * p["values"]:
                    dict_rows.append([ds, f"`{n}`", fmt_int(p["nd"]), "values are GUIDs — meaningless without a reference table"])
                    warn(ds, f"`{n}` contains GUIDs instead of readable values")
    if has(1, "hospitalization_code"):
        dict_rows.append([1, "`hospitalization_code` parts", "—", "region / organization / profile codes embedded in the id"])
    if has(1, "hospitalization_dt", "refusal_dt") and not any("status" in p["name"] for p in summaries[1]["cols"]):
        dict_rows.append([1, "(status)", "—", "no explicit status column — status must be derived from hospitalization_dt / refusal_dt"])
    if has(3, "region_in"):
        dict_rows.append([3, "`region_in`, `attach_region`", fmt_int(next(p["nd"] for p in summaries[3]["cols"] if p["name"] == "region_in")),
                          "region NAMES — need mapping to the numeric region codes of ds1/ds2"])
    L += md_table(["ds", "column", "distinct", "why"], dict_rows) if dict_rows else ["- none detected"]
    L.append("")
    return L


# --------------------------------------------------------------------- main
def main() -> int:
    if not RAW.is_dir():
        print(f"data/raw not found at {RAW}", file=sys.stderr)
        return 1
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="inventory_duckdb_"))
    started = time.time()
    try:
        con = duckdb.connect(str(tmpdir / "inventory.duckdb"))
        con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}'")
        con.execute(f"SET temp_directory='{tmpdir / 'spill'}'")
        con.execute("SET preserve_insertion_order=true")

        folders = []
        for p in RAW.iterdir():
            m = re.match(r"^(\d+)", p.name)
            if p.is_dir() and m:
                folders.append((int(m.group(1)), p))
        folders.sort()

        sections, summaries = [], {}
        for ds, folder in folders:
            print(f"[{time.time() - started:6.1f}s] dataset {ds}: {folder.name} …", flush=True)
            try:
                lines, summary = analyse_dataset(con, ds, folder, tmpdir)
            except Exception as e:  # keep going; record the failure in the report
                warn(ds, f"inventory failed: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
                lines = [f"## Dataset {ds} — {DATASET_TITLES.get(ds, folder.name)}", "",
                         f"**Inventory failed:** `{type(e).__name__}: {str(e).splitlines()[0][:300]}`", ""]
                summary = {"ds": ds, "title": DATASET_TITLES.get(ds, folder.name), "table": None, "status": "failed"}
            sections.append(lines)
            summaries[ds] = summary

        print(f"[{time.time() - started:6.1f}s] join keys …", flush=True)
        joins = join_section(con, summaries)

        head = ["# Data inventory — step 1", "",
                f"Generated {dt.datetime.now():%Y-%m-%d %H:%M} by `scripts/00_inventory.py` "
                f"(DuckDB {duckdb.__version__}, pandas {pd.__version__}). Raw data is read-only; nothing is modified.", "",
                "## Overview", ""]
        rows = []
        for ds, s in sorted(summaries.items()):
            rng = "—"
            if s.get("table"):
                mdc = main_date_column(s["cols"], s["total"])
                p = next((c for c in s["cols"] if c["name"] == mdc), None)
                rng = f"{str(p['tmin'])[:10]} → {str(p['tmax'])[:10]}" if p else "no event date"
            rows.append([ds, s["title"], s.get("n_files", 0), fmt_size(s.get("size", 0)), fmt_int(s.get("total")),
                         s.get("n_cols", "—"), rng, s.get("status", "")])
        head += md_table(["ds", "dataset", "files", "size", "rows", "cols", "main date range", "status"], rows)
        head += ["", "Contents: one section per dataset, then **Join keys and observations** at the end.", ""]

        body = head + [l for sec in sections for l in sec + ["---", ""]] + joins
        REPORT.write_text("\n".join(body) + "\n", encoding="utf-8")

        # compact console summary
        print("\n" + "=" * 100)
        print(f"{'ds':<3}{'files':>6}{'size':>10}{'rows':>13}{'cols':>6}  {'main date range':<26}status")
        for r in rows:
            print(f"{r[0]:<3}{r[2]:>6}{r[3]:>10}{r[4]:>13}{str(r[5]):>6}  {r[6]:<26}{r[7]}")
        by_level = {lvl: [w for w in warnings_global if severity(w) == lvl] for lvl in ("critical", "notable", "minor")}
        print(f"\n{len(warnings_global)} observations flagged "
              f"({len(by_level['critical'])} critical, {len(by_level['notable'])} notable, {len(by_level['minor'])} minor). Critical:")
        for w in by_level["critical"]:
            print("  - " + w.replace("**", "").replace("`", ""))
        print(f"\nReport: {REPORT.relative_to(ROOT)}   ({time.time() - started:.0f}s)")
        con.close()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
