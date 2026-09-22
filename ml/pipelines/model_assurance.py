#!/usr/bin/env python3
"""Publish the deterministic Model Assurance v1 bundle; never recompute ML evidence."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from hqai_ml.assurance import build_assurance, verify_evidence_sources, write_assurance_bundle

ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "ml" / "configs" / "model_assurance.yaml")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts" / "model_assurance")
    parser.add_argument("--generated-at", help="audit timestamp; excluded from assurance identity")
    parser.add_argument(
        "--require-evidence-files",
        action="store_true",
        help="fail when ignored local evidence manifests are absent",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    generated_at = args.generated_at or dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    payload = build_assurance(args.config, generated_at=generated_at)
    verification = verify_evidence_sources(ROOT, payload, require_present=args.require_evidence_files)
    output = args.output_root / payload["assurance_id"] / "model_assurance.json"
    write_assurance_bundle(payload, output)
    print(f"model assurance: {output}")
    print(f"assurance identity: {payload['assurance_identity_sha256']}")
    print(
        "source verification: "
        f"{verification['verified_run_manifests']} verified, "
        f"{verification['absent_run_manifests']} absent (versioned references retained)"
    )


if __name__ == "__main__":
    main()
