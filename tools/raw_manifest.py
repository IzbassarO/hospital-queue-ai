#!/usr/bin/env python3
"""Provenance manifest of the raw Ministry of Health files: what we were given and what we actually read.

The raw files themselves are never committed (16 GB, `data/` is gitignored), so a reviewer cannot check that the
numbers in the repository come from the files the organisers handed out. This writes a manifest they can check
against their own copy: per file the size, SHA-256, header and row count, and per dataset whether the ingest
pipeline reads it (`docs/data.md` §1).

    make raw-manifest                  # data/raw -> docs/raw-manifest.json
    python tools/raw_manifest.py --raw-dir /path/to/raw --out /path/to/manifest.json
    python tools/raw_manifest.py --verify docs/raw-manifest.json      # re-hash and compare

Hashing is read-only and streams the files; datasets that the pipeline does not read are recorded by size and
header only (`--hash-all` hashes them too). Row counts come from a byte-level newline count, not a CSV parse.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = REPO_ROOT / "data" / "raw"
DEFAULT_OUT = REPO_ROOT / "docs" / "raw-manifest.json"
BLOCK = 8 * 1024 * 1024

# Folder name -> what the file is and whether ml/pipelines/ingest.py reads it (docs/data.md §1).
DATASETS: dict[str, dict[str, object]] = {
    "1 dataset": {
        "content": "Направления на плановую госпитализацию в стационары (ИС БГ)",
        "system": "ИС «Бюро госпитализации»",
        "ingested": True,
        "used_for": "fact_referral, dim_region/dim_profile/dim_organization/dim_icd, agg_daily_*",
    },
    "2 dataset": {
        "content": "Пациенты, ожидающие плановой госпитализации (ИС БГ)",
        "system": "ИС «Бюро госпитализации»",
        "ingested": True,
        "used_for": "только список region_origin_code для dim_region (та же когорта, что и набор 1)",
    },
    "3 dataset": {
        "content": "Отказы в госпитализации в приёмном покое (ИС БГ)",
        "system": "ИС «Бюро госпитализации»",
        "ingested": True,
        "used_for": "fact_admission_refusal, agg_daily_admission_refusals, регион стационара",
    },
    "4 dataset": {
        "content": "Количество пролеченных случаев в разрезе МО (ЕРСБ)",
        "system": "ИС ЕРСБ",
        "ingested": True,
        "used_for": "ersb_snapshot (статичный признак пропускной способности)",
    },
    "5 dataset": {
        "content": "Факты проведённых вакцинаций (ИС Вакцинация)",
        "system": "ИС «Вакцинация»",
        "ingested": False,
        "used_for": "не загружается: нет ключа связи с направлениями (docs/project-evidence-index.md §11)",
    },
    "6 dataset": {
        "content": "Отказы от вакцинации и противопоказания (ИС Вакцинация)",
        "system": "ИС «Вакцинация»",
        "ingested": False,
        "used_for": "не загружается",
    },
    "7 dataset": {
        "content": "Онкобольные с впервые установленным диагнозом (ИС ЭРОБ)",
        "system": "ИС ЭРОБ",
        "ingested": False,
        "used_for": "не загружается",
    },
    "8 dataset": {
        "content": "Запущенность злокачественных новообразований по локализациям (ИС ЭРОБ)",
        "system": "ИС ЭРОБ",
        "ingested": False,
        "used_for": "не загружается",
    },
}

SOURCE = {
    "publisher": "Министерство здравоохранения Республики Казахстан",
    "distributed_by": "GovTech Camp 2026 (АО «Национальные информационные технологии»)",
    "access": "папка с датасетами, выданная участникам программы; открытые обезличенные данные",
    "note": "Файлы не входят в репозиторий (16 ГБ, data/ в .gitignore). Манифест позволяет сверить копию.",
}


def sha256_and_rows(path: Path, *, hash_file: bool) -> tuple[str | None, int | None]:
    """Stream the file once: SHA-256 (optional) and, for CSV, the number of data rows (newlines minus the header)."""
    digest = hashlib.sha256() if hash_file else None
    countable = path.suffix.lower() in {".csv", ".tsv", ".txt"}
    newlines = 0
    last_byte = b""
    with path.open("rb") as stream:
        while block := stream.read(BLOCK):
            if digest is not None:
                digest.update(block)
            if countable:
                newlines += block.count(b"\n")
                last_byte = block[-1:]
    if not countable:
        return (digest.hexdigest() if digest else None), None
    rows = newlines if last_byte == b"\n" else newlines + 1
    return (digest.hexdigest() if digest else None), max(rows - 1, 0)


def header_of(path: Path) -> str | None:
    """The CSV header line; None for formats whose first bytes are not a header (XLSX)."""
    if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
        return None
    with path.open("rb") as stream:
        line = stream.readline(64 * 1024)
    return line.decode("utf-8-sig", errors="replace").rstrip("\r\n")


def build(raw_dir: Path, *, hash_all: bool) -> dict:
    if not raw_dir.is_dir():
        raise SystemExit(f"raw directory not found: {raw_dir}")
    datasets = []
    for folder in sorted(raw_dir.iterdir(), key=lambda p: p.name):
        if not folder.is_dir():
            continue
        meta = DATASETS.get(folder.name, {"content": "unknown", "ingested": False, "used_for": "unknown"})
        hash_files = bool(meta["ingested"]) or hash_all
        files = []
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or path.name.startswith("."):
                continue
            digest, rows = sha256_and_rows(path, hash_file=hash_files)
            entry: dict[str, object] = {"file": path.name, "bytes": path.stat().st_size}
            if rows is not None:
                entry["rows"] = rows
            header = header_of(path)
            if header is not None:
                entry["header"] = header
            if digest:
                entry["sha256"] = digest
            files.append(entry)
            shown = f"{rows:,} rows" if rows is not None else "binary"
            print(f"  {folder.name}/{path.name}: {entry['bytes']:,} B, {shown}", flush=True)
        datasets.append(
            {
                "folder": folder.name,
                **meta,
                "file_count": len(files),
                "bytes": sum(f["bytes"] for f in files),
                "rows": sum(f.get("rows", 0) for f in files),
                "hashed": hash_files,
                "files": files,
            }
        )
    return {
        "description": "Provenance of the raw MoH files behind every number in this repository (tools/raw_manifest.py)",
        "source": SOURCE,
        "datasets": datasets,
        "totals": {
            "files": sum(d["file_count"] for d in datasets),
            "bytes": sum(d["bytes"] for d in datasets),
            "ingested_bytes": sum(d["bytes"] for d in datasets if d["ingested"]),
        },
    }


def verify(manifest_path: Path, raw_dir: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bad = 0
    for dataset in manifest["datasets"]:
        for entry in dataset["files"]:
            path = raw_dir / dataset["folder"] / entry["file"]
            if not path.is_file():
                print(f"MISSING {dataset['folder']}/{entry['file']}")
                bad += 1
                continue
            if path.stat().st_size != entry["bytes"]:
                print(f"SIZE    {dataset['folder']}/{entry['file']}")
                bad += 1
                continue
            if "sha256" not in entry:
                continue
            digest, _ = sha256_and_rows(path, hash_file=True)
            if digest != entry["sha256"]:
                print(f"SHA256  {dataset['folder']}/{entry['file']}")
                bad += 1
    print(f"{'ok' if not bad else f'{bad} mismatches'}: {manifest['totals']['files']} files checked")
    return 1 if bad else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--hash-all", action="store_true", help="also hash the datasets the pipeline does not read")
    parser.add_argument("--verify", type=Path, help="re-hash the files and compare with this manifest")
    args = parser.parse_args()
    if args.verify:
        return verify(args.verify, args.raw_dir)
    manifest = build(args.raw_dir, hash_all=args.hash_all)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    totals = manifest["totals"]
    print(
        f"{args.out}: {totals['files']} files, {totals['bytes'] / 1e9:.1f} GB "
        f"({totals['ingested_bytes'] / 1e9:.1f} GB ingested)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
