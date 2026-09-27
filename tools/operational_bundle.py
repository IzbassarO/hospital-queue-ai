"""Offline projection of the explicitly frozen final-test evidence; never imported by the API.

No fitting, scoring, calibration, selection, ranking or severity calculation. All model
values come from checksummed artifacts. See docs/demo-publication-slice-5.md.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.operational_intelligence import (  # noqa: E402
    ForecastPublicationRow,
    OperationalIntelligenceBundle,
    SignalPublicationRow,
)
from app.services.model_assurance import parse_assurance_bundle  # noqa: E402
from app.services.operational_intelligence import parse_bundle  # noqa: E402

ASSURANCE_IDENTITY = "f504defefdd87bcbb01c670b68469ba4c0e016be7f40ca89452baf69b73f39f5"
ASSURANCE_PATH = "artifacts/model_assurance/model-assurance-6b5-v1/model_assurance.json"
# Accepted defaults of the CLI parameters (--origin, --publication-id, --run KEY=RUN-ID). They are explicit inputs,
# not discovery: every run id must be the one recorded in Model Assurance and its manifest must carry the origin.
ORIGIN = "2025-03-17"
PUBLICATION = "operational-intelligence-slice5-final-test-2025-03-17-v1"
# No discovery by newest directory, mtime, or mutable current pointer.
SOURCES = {
    "flow_forecast": ("flow_point_forecast", "flow-evidence-6b2b1-corrected-v3"),
    "flow_quantile": ("flow_quantile_forecast", "flow-quantile-6b2b2-real-v1"),
    "flow_calibration": ("flow_temporal_calibration", "flow-calibration-6b2b2b-real-v1"),
    "flow_hierarchy": ("flow_hierarchical_coherence", "flow-hierarchy-6b2b3-real-v1"),
    "flow_pressure": ("preventive_flow_pressure", "flow-pressure-6b2c1-real-v2"),
    "signal_prioritization": ("signal_prioritization", "signal-prioritization-6b2c2-real-v2"),
    "flow_scenario": ("forecast_stress_test", "flow-scenario-6b3-real-v1"),
    "decision_alternatives": ("decision_alternatives", "decision-alternatives-6b4-real-v3"),
}
FORECAST_KEYS = ["flow_forecast", "flow_quantile", "flow_calibration", "flow_hierarchy"]
SIGNAL_KEYS = [*FORECAST_KEYS, "flow_pressure", "signal_prioritization"]
OUTPUT_DIR = "artifacts/operational_intelligence"


@dataclass(frozen=True)
class Publication:
    """Explicit inputs of one projection: the origin, the publication id and the run id behind every source key."""

    origin: str = ORIGIN
    publication_id: str = PUBLICATION
    runs: Mapping[str, str] = field(default_factory=lambda: {k: run for k, (_, run) in SOURCES.items()})

    def __post_init__(self) -> None:
        dt.date.fromisoformat(self.origin)
        unknown, missing = set(self.runs) - set(SOURCES), set(SOURCES) - set(self.runs)
        require(not unknown, f"unknown source keys: {sorted(unknown)}; known: {sorted(SOURCES)}")
        require(not missing, f"every source key needs a run id: {sorted(missing)}")
        require(all(v and "/" not in v and v not in {".", ".."} for v in self.runs.values()), "invalid run id")

    @property
    def sources(self) -> dict[str, tuple[str, str]]:
        return {key: (capability, self.runs[key]) for key, (capability, _) in SOURCES.items()}

    def limitations(self) -> list[str]:
        first = f"Retrospective final-test origin {self.origin}; not a live forecast or current hospital condition."
        return [first, *LIMITATIONS]


def parse_runs(pairs: list[str] | None, sources_json: Path | None) -> dict[str, str]:
    """Run ids from --sources-json (a {key: run-id} object) overlaid by repeated --run KEY=RUN-ID."""
    runs = {k: run for k, (_, run) in SOURCES.items()}
    if sources_json is not None:
        loaded = read_json(sources_json)
        require(isinstance(loaded, dict) and all(isinstance(v, str) for v in loaded.values()), "sources json shape")
        runs |= loaded
    for pair in pairs or []:
        key, sep, run_id = pair.partition("=")
        require(bool(sep) and key and run_id, f"--run expects KEY=RUN-ID, got {pair!r}")
        runs[key] = run_id
    return runs


def accepted_origins(run: dict) -> set[str]:
    """Origins a run manifest declares in its temporal protocol (empty when the protocol names none)."""
    found: set[str] = set()
    for protocol in (run.get("temporal_protocols") or {}).values():
        if protocol.get("final_test_origin"):
            found.add(str(protocol["final_test_origin"]))
        found.update(str(o) for o in protocol.get("origins") or [])
    return found


LIMITATIONS = [
    "historical_flow_proxy_v1 compares historical flow; physical capacity is not measured or checked.",
    "Human review required; no autonomous routing or causal effect claim.",
    "Freshness UNKNOWN: no approved refresh SLA; publication time is not evidence freshness.",
    "Selected hierarchy central values and level-local calibrated intervals are separate evidence; "
    "no probabilistic reconciliation or joint distribution is claimed.",
    "Only published primary Inbox, data-quality, low-volume attention and flagged observed-anomaly views "
    "are projected as signals; normal registrations and secondary research signals are not primary warnings.",
    "Scenario and decision alternatives remain evaluation/human-review only and are not operational signals.",
]
SUPPORT = {"supported": "DIRECT_SUPPORTED", "limited_history": "FALLBACK_LIMITED", "no_history": "UNSUPPORTED"}
FALLBACK = {
    "not_applicable": "NOT_APPLICABLE",
    "regional_fallback": "REGION_PROFILE_FALLBACK",
    "no_history_deterministic_zero": "UNSUPPORTED",
    "national_historical_quantile_proxy": "OTHER_FALLBACK",
}
UNCERTAINTY = {
    "level_local_calibrated": "CALIBRATED",
    "level_local_calibrated_not_reconciled": "CALIBRATED",
    "calibration_support_insufficient": "INSUFFICIENT_CALIBRATION_SUPPORT",
    "uncertainty_unavailable": "UNAVAILABLE",
    "national_proxy_not_predictive_distribution": "UNAVAILABLE",
}


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def evidence_hash(value: object) -> str:
    # The frozen registry's canonical identity format differs from the publication format.
    raw = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n"
    return hashlib.sha256(raw.encode()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Evidence:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.files: dict[str, str] = {}

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        require(path.is_relative_to(self.root / "artifacts"), "source path must stay inside artifacts")
        return path

    def json(self, relative: str) -> dict:
        path = self.path(relative)
        self.files[relative] = file_hash(path)
        return read_json(path)

    def artifact(self, reference: dict) -> Path:
        directory = self.path("artifacts/" + reference["path"])
        relative = directory.relative_to(self.root).as_posix()
        manifest = self.json(relative + "/artifact-manifest.json")
        require(manifest["content_sha256"] == reference["sha256"], f"artifact identity mismatch: {relative}")
        require(evidence_hash({"files": manifest["files"]}) == reference["sha256"], "manifest content hash mismatch")
        actual = sorted(
            p.relative_to(directory).as_posix()
            for p in directory.rglob("*")
            if p.is_file() and p.name != "artifact-manifest.json"
        )
        require(actual == [f["path"] for f in manifest["files"]], f"partial/unexpected artifact files: {relative}")
        for entry in manifest["files"]:
            path = self.path(relative + "/" + entry["path"])
            require(path.is_relative_to(directory), "artifact file escapes directory")
            digest = file_hash(path)
            require(
                path.stat().st_size == entry["bytes"] and digest == entry["sha256"],
                f"artifact checksum mismatch: {path.name}",
            )
            self.files[path.relative_to(self.root).as_posix()] = digest
        return directory

    def run_manifest(self, key: str, run_id: str, origin: str) -> dict:
        """Read one accepted run manifest; refuse a missing directory or an origin the run does not declare."""
        relative = f"artifacts/runs/{run_id}/run.json"
        require(
            self.path(relative).exists(),
            f"{key}: no accepted run directory artifacts/runs/{run_id}; the builder never discovers runs by newest "
            "directory, pass --run {key}=<accepted-run-id>",
        )
        run = self.json(relative)
        declared = accepted_origins(run)
        require(
            not declared or origin in declared,
            f"{key}: origin {origin} is not declared by run {run_id} (accepted: {sorted(declared)}); pass --run "
            f"{key}=<run-id> for an accepted run at that origin",
        )
        return run

    def verify(self, publication: Publication | None = None) -> tuple[dict, dict, dict, dict]:
        publication = publication or Publication()
        payload = self.json(ASSURANCE_PATH)
        parsed = parse_assurance_bundle(canonical(payload))
        require(parsed.bundle.assurance_identity_sha256 == ASSURANCE_IDENTITY, "unaccepted Model Assurance identity")
        capabilities = {c["capability_id"]: c for c in payload["capabilities"]}
        require(len(capabilities) == 13, "expected 13 assurance capabilities")
        provenance, summaries, evaluations = {}, {}, {}
        # Verify every available run identity in Assurance, including separate Patient Journey evidence.
        for capability in capabilities.values():
            run = self.json(capability["run_manifest"])
            ids = capability["identities"]
            for key, value in {
                "run_id": run["run_id"],
                "scientific_identity_sha256": run["scientific_identity_sha256"],
                "dataset_identity_sha256": run["dataset"]["identity_sha256"],
                "config_identity_sha256": run["configuration"]["sha256"],
                "code_identity_sha256": run["code"]["source"]["sha256"],
            }.items():
                require(ids[key]["status"] == "AVAILABLE" and ids[key]["value"] == value, f"assured {key} mismatch")
            require(
                evidence_hash(run["scientific_identity"]) == run["scientific_identity_sha256"],
                "run scientific hash mismatch",
            )
            require(run["status"] == "completed", "incomplete accepted run")
        for key, (capability_id, run_id) in publication.sources.items():
            cap = capabilities[capability_id]
            ids = cap["identities"]
            require(
                ids["run_id"]["value"] == run_id,
                f"{key}: run {run_id} is not the accepted run recorded in Model Assurance ({ids['run_id']['value']})",
            )
            require(cap["evidence_status"] == "ACCEPTED", "source is not accepted")
            expected_eligibility = "ELIGIBLE_AFTER_INGESTION" if key in SIGNAL_KEYS else "EVALUATION_ONLY"
            require(cap["product_consumption_status"] == expected_eligibility, "source eligibility changed")
            run = self.run_manifest(key, run_id, publication.origin)
            artifact = run["artifacts"]["load_forecast"]
            require(artifact["sha256"] == ids["artifact_sha256"]["value"], "assured artifact hash mismatch")
            summary_dir = self.artifact(artifact)
            summary = read_json(summary_dir / "summary.json")
            require(
                summary["run_id"] == run_id
                and summary["scientific_identity_sha256"] == run["scientific_identity_sha256"],
                "summary identity mismatch",
            )
            summaries[key] = summary
            provenance[key] = {
                name: ids[name]["value"]
                for name in (
                    "run_id",
                    "scientific_identity_sha256",
                    "artifact_sha256",
                    "dataset_identity_sha256",
                    "config_identity_sha256",
                    "code_identity_sha256",
                )
            }
            if key not in {"flow_hierarchy", "flow_pressure", "signal_prioritization"}:
                continue
            checkpoints = []
            for path in sorted((self.root / "artifacts/runs" / run_id / "checkpoints").glob("*.json")):
                cp = self.json(path.relative_to(self.root).as_posix())
                expected = evidence_hash(
                    {
                        "run_scientific_identity": run["scientific_identity_sha256"],
                        "key": cp["key"],
                        "parameters": cp["parameters"],
                    }
                )
                require(
                    cp["scientific_identity_sha256"] == expected
                    and cp["status"] == "completed"
                    and cp["evaluation"]["status"] == "completed",
                    "checkpoint identity/status mismatch",
                )
                checkpoints.append(cp)
            summary_cp = [cp for cp in checkpoints if cp["artifact"] == artifact]
            require(len(summary_cp) == 1, "missing/ambiguous summary checkpoint")
            evaluation_id = summary_cp[0]["parameters"]["evaluation_checkpoint"]
            candidates = [cp for cp in checkpoints if evidence_hash(cp["key"]) == evaluation_id]
            require(len(candidates) == 1, "missing/ambiguous evaluation checkpoint")
            evaluations[key] = self.artifact(candidates[0]["artifact"])
        # Cross-run lineage is anchored in the checksummed accepted summaries.
        for child, parent in [("flow_pressure", "flow_hierarchy"), ("signal_prioritization", "flow_pressure")]:
            lineage = summaries[child]["source_lineage"]
            require(lineage["source_run_id"] == provenance[parent]["run_id"], "mixed source run")
            require(
                lineage["source_scientific_identity"] == provenance[parent]["scientific_identity_sha256"],
                "mixed scientific lineage",
            )
            manifest = read_json(evaluations[parent] / "artifact-manifest.json")
            require(lineage["evaluation_artifact_sha256"] == manifest["content_sha256"], "mixed evaluation artifact")
        return payload, provenance, summaries, evaluations


def date(value) -> str | None:
    import pandas as pd

    return None if pd.isna(value) else pd.Timestamp(value).date().isoformat()


def number(value) -> float | None:
    if value is None or str(value) == "<NA>" or math.isnan(float(value)):
        return None
    require(math.isfinite(float(value)), "non-finite source number")
    return float(value)


def statuses(row: dict) -> dict:
    support = SUPPORT[row["support_status"]]
    fallback = FALLBACK[row["fallback_status"]]
    if support == "DIRECT_SUPPORTED" and fallback != "NOT_APPLICABLE":
        support = "FALLBACK_LIMITED"
    return {
        "support_status": support,
        "fallback_status": fallback,
        "uncertainty_status": UNCERTAINTY[row["uncertainty_status"]],
    }


def forecast_row(row: dict, limitations: list[str]) -> dict:
    state = statuses(row)
    aggregate = row["level"] != "hospital"
    raw = None
    facts = [
        f"Accepted source support={row['support_status']}; fallback={row['fallback_status']}; "
        f"uncertainty={row['uncertainty_status']}; central source={row['forecast_source']}."
    ]
    limits = list(limitations)
    if row["raw_quantile_semantics"] == "unchanged_model_evidence":
        values = [number(row[f"raw_p{q}"]) for q in (10, 50, 90)]
        require(all(v is not None for v in values), "partial raw quantiles")
        raw = dict(zip(("p10", "p50", "p90"), values, strict=True)) | {"semantics": "UNCHANGED_MODEL_EVIDENCE"}
    else:
        require(
            row["raw_quantile_semantics"] == "historical_region_quantile_sum_proxy_not_national_distribution"
            and row["level"] == "national",
            "unknown quantile semantics",
        )
        facts.append(
            "Historical region quantile sum proxy (not national predictive quantiles): "
            + json.dumps({f"p{q}": number(row[f"raw_p{q}"]) for q in (10, 50, 90)}, sort_keys=True)
        )
        limits.append("National quantile sums are proxy evidence only; no national predictive interval is available.")
    band = None
    if state["uncertainty_status"] == "CALIBRATED":
        require(row["calibration_status"] == "calibrated", "calibration state mismatch")
        band = {
            "lower": number(row["level_local_interval_80_lower"]),
            "upper": number(row["level_local_interval_80_upper"]),
            "nominal_coverage": 0.8,
            "calibration_status": "CALIBRATED",
            "support_class": row["calibration_support_class"],
            "calibration_version": row["calibration_version"],
        }
    central = number(row["forecast_value"])
    semantics = "BOTTOM_UP_CENTRAL" if aggregate else "POINT_FORECAST"
    if not aggregate and raw is not None and central == raw["p50"]:
        semantics = "P50"
    return ForecastPublicationRow.model_validate(
        {
            "series_id": row["series_id"],
            "level": row["level"],
            "origin": date(row["origin"]),
            "target_date": date(row["target_date"]),
            "horizon": int(row["horizon"]),
            "target": row["target"],
            "org_code": row["org_code"] if not aggregate else None,
            "region_code": row["region_code"] if row["level"] != "national" else None,
            "profile_code": row["profile_code"],
            "central_value": central,
            "central_semantics": semantics,
            "raw_quantiles": raw,
            "calibrated_uncertainty": band,
            "calibration_status": "CALIBRATED"
            if band
            else (
                "INSUFFICIENT_SUPPORT"
                if state["uncertainty_status"] == "INSUFFICIENT_CALIBRATION_SUPPORT"
                else "NOT_APPLICABLE"
            ),
            "prediction_source": "BOTTOM_UP_AGGREGATE"
            if aggregate
            else {
                "direct_quantile_ml": "DIRECT",
                "parent_scaled_direct_quantile_ml": "REGION_PROFILE_FALLBACK",
                "deterministic_own_history_fallback": "UNSUPPORTED",
            }[row["forecast_source"]],
            "hierarchy_status": row["hierarchy_status"],
            **state,
            "provenance_keys": FORECAST_KEYS,
            "evidence_facts": facts,
            "limitations": limits,
        }
    ).model_dump(mode="json")


def signal_row(row: dict, limitations: list[str], view: str) -> dict:
    facts = list(row.get("evidence_facts", []))
    facts.append(f"Accepted publication view: {view}.")
    if row["signal_type"] == "observed_unusual_flow":
        require(row["anomaly_status"] in {"UNUSUAL_HIGH", "UNUSUAL_LOW"}, "unflagged observed row")
        result = {
            "signal_id": row["signal_id"],
            "signal_type": row["signal_type"],
            "series_id": row["series_id"],
            "origin": date(row["forecast_origin"]),
            "target": "registrations",
            "org_code": row["hospital_id"],
            "region_code": row["region_id"],
            "profile_code": row["profile_id"],
            "severity": row["severity"],
            "headline": "Observed unusual registration flow",
            "concise_reason": (
                "Published weekly residual differs from its historical robust reference; no causal claim."
            ),
            "support_status": "DIRECT_SUPPORTED",
            "fallback_status": "NOT_APPLICABLE",
            "uncertainty_status": "UNAVAILABLE",
            "observed_anomaly_status": row["anomaly_status"],
            "observed_anomaly_present": True,
            "data_freshness": date(row["data_freshness"]),
            "reason_codes": list(row["reason_codes"]),
            "anomaly_evidence": {
                k: row[k]
                for k in (
                    "observed_value",
                    "weekly_residual",
                    "reference_median_residual",
                    "reference_mad",
                    "robust_z",
                    "reference_sample_count",
                    "causal_claim",
                )
            },
        }
        result["anomaly_evidence"]["reference_max_date"] = date(row["reference_max_date"])
        facts.append("Support refers to the observed residual reference, not calibrated forecast uncertainty.")
    else:
        require(row["threshold_semantics"] == "historical_flow_proxy_v1", "non-historical pressure basis")
        result = {
            k: row[k]
            for k in (
                "signal_id",
                "signal_type",
                "series_id",
                "target",
                "org_code",
                "region_code",
                "profile_code",
                "severity",
                "headline",
                "concise_reason",
                "materiality_status",
                "threshold_status",
                "observed_anomaly_status",
            )
        }
        result |= statuses(row)
        result |= {
            "origin": date(row["origin"]),
            "inbox_rank": int(row["inbox_rank"]) if number(row["inbox_rank"]) is not None else None,
            "pressure_basis": row["threshold_semantics"],
            "observed_anomaly_present": bool(row["observed_anomaly_present"]),
            "first_crossing_date": date(row["first_crossing_date"]),
            "data_freshness": date(row["data_freshness"]),
            "reason_codes": list(row["reason_codes"]),
        }
        for k in ("forecast_value", "threshold_value", "uncertainty_lower", "uncertainty_upper", "lead_time_days"):
            result[k] = number(row[k])
        facts.append(
            f"Published severity evidence date: {date(row['severity_evidence_date'])}; "
            f"horizon: {int(row['severity_evidence_horizon'])}."
        )
        facts.append(
            f"Accepted source support={row['support_status']}; fallback={row['fallback_status']}; "
            f"uncertainty={row['uncertainty_status']}."
        )
    result |= {"provenance_keys": SIGNAL_KEYS, "evidence_facts": facts, "limitations": limitations}
    return SignalPublicationRow.model_validate(result).model_dump(mode="json")


def build(root: Path, publication: Publication | None = None) -> tuple[dict, dict]:
    import pandas as pd

    publication = publication or Publication()
    limitations = publication.limitations()
    evidence = Evidence(root)
    assurance, provenance, summaries, evaluations = evidence.verify(publication)
    print("Verified accepted runs, summary identities and evaluation file checksums", flush=True)
    hierarchy = pd.read_parquet(
        evaluations["flow_hierarchy"] / "selected-central-forecast.parquet", filters=[("phase", "==", "final_test")]
    )
    require(
        set(hierarchy.origin.map(date)) == {publication.origin},
        f"final-test forecasts are at origins {sorted(set(hierarchy.origin.map(date)))}, not {publication.origin}",
    )
    counts = hierarchy.groupby(["series_id", "target", "origin"], dropna=False).horizon.agg(list)
    require(all(sorted(v) == list(range(1, 15)) for v in counts), "partial/duplicate 14-day forecast series")
    require(
        set(hierarchy.hierarchy_alternative)
        == {summaries["flow_hierarchy"]["analysis"]["hierarchy_selection"]["selected"]},
        "wrong accepted hierarchy",
    )
    require(
        set(hierarchy.fallback_candidate)
        == {summaries["flow_hierarchy"]["analysis"]["fallback_selection"]["selected"]},
        "wrong accepted fallback",
    )
    forecasts = [
        forecast_row(r, summaries["flow_hierarchy"]["data_limitations"] + [limitations[0], limitations[4]])
        for r in hierarchy.sort_values(["level", "series_id", "target", "target_date"]).to_dict("records")
    ]
    print(f"Projected {len(forecasts)} complete-horizon forecast rows", flush=True)
    signals, view_counts = [], {}
    for view in (
        "top_priority_all",
        "unsupported_data_quality",
        "zero_baseline_low_volume_attention",
        "observed_anomalies",
    ):
        frame = pd.read_parquet(
            evaluations["signal_prioritization"] / "views" / f"{view}.parquet", filters=[("phase", "==", "final_test")]
        )
        origin_column = "forecast_origin" if view == "observed_anomalies" else "origin"
        require(set(frame[origin_column].map(date)) == {publication.origin}, "mixed signal origins")
        for column, key in [
            ("prioritization_scientific_identity", "signal_prioritization"),
            ("signal_scientific_identity", "flow_pressure"),
            ("forecast_scientific_identity", "flow_hierarchy"),
        ]:
            require(set(frame[column]) == {provenance[key]["scientific_identity_sha256"]}, f"mixed {column}")
        require(
            set(frame.dataset_identity) == {provenance["flow_pressure"]["dataset_identity_sha256"]},
            "mixed dataset identity",
        )
        view_counts[view] = len(frame)
        signals.extend(
            signal_row(r, summaries["flow_pressure"]["data_limitations"] + [limitations[0], limitations[2]], view)
            for r in frame.to_dict("records")
        )
    signals.sort(key=lambda r: (r["inbox_rank"] is None, r["inbox_rank"] or 0, r["signal_id"]))
    ranks = [r["inbox_rank"] for r in signals if r["inbox_rank"] is not None]
    require(ranks == list(range(1, view_counts["top_priority_all"] + 1)), "partial or changed canonical ranks")
    forecast_subjects = {(r["series_id"], r["target"], r["origin"]) for r in forecasts}
    require(
        all((r["series_id"], r["target"], r["origin"]) in forecast_subjects for r in signals),
        "signal without forecast subject",
    )
    payload = {
        "schema_version": "operational_intelligence_v1",
        "contract_version": "1.0.0",
        "publication_id": publication.publication_id,
        "publication_identity_sha256": "0" * 64,
        "assurance_identity_sha256": ASSURANCE_IDENTITY,
        "source_code_commit": assurance["source_code_commit"],
        "current_origin": publication.origin,
        "freshness_state": "UNKNOWN",
        "publication_status": "AVAILABLE",
        "generated_at": None,
        "source_provenance": provenance,
        "limitations": limitations,
        "forecasts": forecasts,
        "signals": signals,
    }
    validated = OperationalIntelligenceBundle.model_validate(payload).model_dump(mode="json")
    identity = {k: v for k, v in validated.items() if k not in {"publication_identity_sha256", "generated_at"}}
    validated["publication_identity_sha256"] = hashlib.sha256(canonical(identity)).hexdigest()
    parse_bundle(canonical(validated))
    top = signals[0]
    report = {
        "builder_version": "frozen-final-test-projection-v1",
        "publication_identity_sha256": validated["publication_identity_sha256"],
        "assurance_identity_sha256": ASSURANCE_IDENTITY,
        "source_provenance": provenance,
        "verified_files": evidence.files,
        "forecast_count": len(forecasts),
        "signal_count": len(signals),
        "signal_view_counts": view_counts,
        "forecast_level_counts": hierarchy.level.value_counts().to_dict(),
        "demo_selection": {
            "rule": "lowest published non-null inbox_rank at explicit final-test origin",
            **{
                k: top[k]
                for k in (
                    "signal_id",
                    "inbox_rank",
                    "region_code",
                    "org_code",
                    "profile_code",
                    "origin",
                    "target",
                    "series_id",
                )
            },
        },
    }
    return validated, report


def plan(root: Path, publication: Publication, output: Path) -> dict:
    """What a build would read and which identities it expects; reads small JSON manifests only, writes nothing."""
    evidence = Evidence(root)
    assurance = read_json(evidence.path(ASSURANCE_PATH))
    capabilities = {c["capability_id"]: c for c in assurance["capabilities"]}
    sources = {}
    for key, (capability_id, run_id) in publication.sources.items():
        ids = capabilities[capability_id]["identities"]
        require(
            ids["run_id"]["value"] == run_id,
            f"{key}: run {run_id} is not the accepted run recorded in Model Assurance ({ids['run_id']['value']})",
        )
        run = evidence.run_manifest(key, run_id, publication.origin)
        sources[key] = {
            "capability_id": capability_id,
            "run_id": run_id,
            "run_manifest": f"artifacts/runs/{run_id}/run.json",
            "summary_artifact": "artifacts/" + run["artifacts"]["load_forecast"]["path"],
            "declared_origins": sorted(accepted_origins(run)),
            "expected_scientific_identity_sha256": ids["scientific_identity_sha256"]["value"],
            "expected_artifact_sha256": ids["artifact_sha256"]["value"],
        }
    previous = output / "build-report.json"
    return {
        "action": "plan (nothing written)",
        "origin": publication.origin,
        "publication_id": publication.publication_id,
        "assurance": {"path": ASSURANCE_PATH, "expected_identity_sha256": ASSURANCE_IDENTITY},
        "sources": sources,
        "reads": ["selected-central-forecast.parquet of flow_hierarchy", "views/*.parquet of signal_prioritization"],
        "output": str(output),
        "recorded_publication_identity_sha256": read_json(previous)["publication_identity_sha256"]
        if previous.exists()
        else None,
    }


def add_arguments(parser: argparse.ArgumentParser, default_output: str) -> None:
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root holding artifacts/")
    parser.add_argument("--origin", default=ORIGIN, help=f"explicit final-test origin YYYY-MM-DD (default {ORIGIN})")
    parser.add_argument("--publication-id", default=None, help="publication id (default: the accepted id)")
    parser.add_argument(
        "--run", action="append", metavar="KEY=RUN-ID", help=f"accepted run id per source key ({', '.join(SOURCES)})"
    )
    parser.add_argument("--sources-json", type=Path, help="JSON object {source key: run id}, overlaid by --run")
    parser.add_argument("--out", type=Path, help=f"output directory (default {default_output}/<publication-id>)")
    parser.add_argument("--plan", action="store_true", help="print what would be read and the expected identities")


def write_outputs(output: Path, files: list[tuple[str, dict]]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, value in files:
        path = output / name
        data = canonical(value) + b"\n"
        if path.exists():
            require(path.read_bytes() == data, f"immutable output already exists with different content: {name}")
        else:
            temporary = path.with_suffix(".json.partial")
            temporary.write_bytes(data)
            temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    add_arguments(parser, OUTPUT_DIR)
    args = parser.parse_args()
    publication = Publication(
        origin=args.origin,
        publication_id=args.publication_id or PUBLICATION,
        runs=parse_runs(args.run, args.sources_json),
    )
    output = args.out or args.root / OUTPUT_DIR / publication.publication_id
    if args.plan:
        print(json.dumps(plan(args.root, publication, output), ensure_ascii=False, indent=2))
        return
    bundle, report = build(args.root, publication)
    write_outputs(output, [("operational_intelligence.json", bundle), ("build-report.json", report)])
    print(
        json.dumps(
            {
                "output": str(output),
                "origin": publication.origin,
                "forecasts": report["forecast_count"],
                "signals": report["signal_count"],
                "identity": bundle["publication_identity_sha256"],
            }
        )
    )


if __name__ == "__main__":
    main()
