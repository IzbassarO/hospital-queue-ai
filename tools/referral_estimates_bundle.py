#!/usr/bin/env python3
"""Offline publication of the per-referral journey estimates of one origin_journey run; never imported by the API.

  make referral-estimates-bundle   -> artifacts/referral_estimates/<publication-id>/referral_estimates.json

The run directory is the ML side's output and is read, never re-computed: this tool joins nothing, fits nothing and
scores nothing. It reads `predictions.csv` (one row per referral at the origin), `decision.json` (which model the
pre-committed rule selected), `metrics.json` (the tournament scores and the reliability table of the model that
won), `config.json` and `manifest.json`/`run.json` (the run's own identity hashes), and writes them as one
publication the backend can validate, publish and serve beside the measured waiting list.

Two things this tool decides, and both are published with their definition so a reader can re-apply them:

* the **evidence tier** of each row, renamed from the ML hierarchy level to the four product names
  (hospital_profile / region_profile / profile / national);
* the **refusal-attention threshold** — the upper decile of P(refusal within 30 days) over the whole cohort. It
  is an administrative follow-up cut (check the referral is still valid, reach the patient), never triage, and the
  sentence saying so travels with the number all the way to the screen.

Abstention is a published value, not a blank: when the comparable history holds no admission inside the model's
time grid there is no central interval to quote, and the row carries that reason instead of an empty cell. So is
degeneracy: the served curve is conditional on the wait already served, and past sixty days the comparable
history still at risk is thin enough that the whole 30-day mass lands on one outcome. Those rows are flagged, so
the screen can say "no outcomes in the comparable history" where it would otherwise print a confident 0%.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.referral_estimates import ReferralEstimatesBundle  # noqa: E402
from app.services.referral_estimates import identity_of, parse_bundle  # noqa: E402

RUN_DIR = "ml/hqai_ml/origin_journey/artifacts/b2-origin-2025-03-17-v2"
PUBLICATION = "referral-estimates-origin-2025-03-17-v1"
OUTPUT_DIR = "artifacts/referral_estimates"
# probabilities are published rounded; the backend contract allows exactly this much incoherence and no more
DECIMALS = 6
ATTENTION_QUANTILE = 0.9
BASELINE_MODEL = "aalen_johansen"
HORIZONS = (7, 14, 30)

# the ML hierarchy level -> the product's word for the same thing (i18n turns these into RU/KK sentences)
TIERS = {
    "org_codexprofile_code": "hospital_profile",
    "hospital_region_codexprofile_code": "region_profile",
    "profile_code": "profile",
    "global": "national",
}
NO_WINDOW = "NO_ADMISSION_IN_COMPARABLE_HISTORY"
DEGENERACY_DEFINITION = (
    "Вся вероятностная масса на 30 дней пришлась на один исход (0% или 100%). Кривая условна по уже "
    "отбытому ожиданию, и после 60 дней сопоставимых наблюдений, ещё остающихся под риском, почти не "
    "остаётся: это признак малой опоры, а не уверенности модели."
)

DECISION_RULE = (
    "Метрика и правило зафиксированы до запуска: средний Brier по госпитализации и отказу на 7, 14 и 30 дней. "
    "Кандидат заменяет базовую модель только если он строго улучшает общий показатель и ни в одной группе по "
    "сроку ожидания не ухудшает его больше чем на 0.005. Если правило не прошёл ни один кандидат, работает "
    "базовая модель Aalen—Johansen."
)
ATTENTION_DEFINITION = (
    "Верхний дециль распределения P(отказ ≤ 30 дн.) по всей опубликованной когорте на дату отсчёта; "
    "порог вычислен один раз при сборке публикации и опубликован вместе с ней."
)
ATTENTION_USE = (
    "Административная проверка: убедиться, что направление ещё действительно, и связаться с пациентом. "
    "Это не медицинская оценка, не приоритет госпитализации и не основание отказать."
)
LIMITATIONS = [
    "Оценки origin-time: считаны по истории до даты отсчёта и не знают ни одного исхода после неё.",
    "Это вероятности по сопоставимой истории, а не обещание даты госпитализации конкретному пациенту.",
    "Источник начинается 01.01.2025, поэтому длинные ожидания, начавшиеся в 2024 году, в обучении отсутствуют.",
    "Профили дневного стационара (DH) исключены из когорты.",
    "Пустое окно госпитализации — это отказ модели от оценки, а не «ноль дней»: в сопоставимой истории нет ни "
    "одной госпитализации в пределах сетки модели.",
    "estimate_tier — происхождение кривой (стационар, регион, профиль, страна), а не уверенность в числе.",
    "calibration — ретроспектива по всей когорте: она проверяет оценки постфактум и ни во что не подаётся.",
]


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def head_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"cannot read the current commit (pass --source-code-commit): {exc}") from exc
    return result.stdout.strip()


def read_json(run: Path, name: str) -> dict:
    try:
        return json.loads((run / name).read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"{run / name}: cannot read the run artefact: {exc}") from exc


def probability(value: str, where: str) -> float:
    number = round(float(value), DECIMALS)
    if not 0.0 <= number <= 1.0:
        raise SystemExit(f"{where}: probability {number} lies outside [0, 1]")
    return number


def selection_block(decision: dict, metrics: dict) -> dict:
    """The tournament exactly as the run decided it, with each model's per-horizon score from metrics.json."""

    def by_horizon(model: str) -> dict[str, float]:
        horizons = metrics[model]["overall"]["by_horizon"]
        scores = {}
        for horizon in HORIZONS:
            outcomes = horizons[str(horizon)]
            pair = [outcomes["hospitalized"]["brier"], outcomes["refused"]["brier"]]
            scores[str(horizon)] = round(statistics.mean(pair), DECIMALS)
        return scores

    candidates = [
        {
            "model_key": BASELINE_MODEL,
            "role": "baseline",
            "accepted": None,
            "overall_mean_brier": round(
                metrics[BASELINE_MODEL]["overall"]["mean_admission_and_refusal_brier"], DECIMALS
            ),
            "overall_delta": None,
            "worst_bucket_delta": None,
            "strict_overall_improvement": None,
            "within_bucket_tolerance": None,
            "brier_by_horizon": by_horizon(BASELINE_MODEL),
        }
    ]
    for model, row in sorted(decision["candidate_decisions"].items()):
        candidates.append(
            {
                "model_key": model,
                "role": "candidate",
                "accepted": bool(row["accepted"]),
                "overall_mean_brier": round(row["overall_mean_brier"], DECIMALS),
                "overall_delta": round(row["overall_delta"], DECIMALS),
                "worst_bucket_delta": round(row["worst_bucket_delta"], DECIMALS),
                "strict_overall_improvement": bool(row["strict_overall_improvement"]),
                "within_bucket_tolerance": bool(row["within_bucket_tolerance"]),
                "brier_by_horizon": by_horizon(model),
            }
        )
    tolerances = {row["tolerance"] for row in decision["candidate_decisions"].values()}
    if len(tolerances) != 1:
        raise SystemExit("the run recorded more than one bucket tolerance; the decision rule is not one rule")
    return {
        "metric": decision["precommitted_metric"],
        "decision_rule": DECISION_RULE,
        "tolerance": tolerances.pop(),
        "require_strict_overall_improvement": True,
        "selected_model": decision["selected_model"],
        "fallback_used": bool(decision["fallback_used"]),
        "candidates": candidates,
    }


def calibration_block(metrics: dict, selected: str, rows: int) -> dict:
    """The reliability table of the model that serves, over the whole cohort. Hindsight, and marked as such."""
    bins = []
    horizons = metrics[selected]["overall"]["by_horizon"]
    for horizon in HORIZONS:
        for outcome in ("hospitalized", "refused"):
            for entry in horizons[str(horizon)][outcome]["reliability"]:
                bins.append(
                    {
                        "horizon_days": horizon,
                        "outcome": outcome,
                        "bin_index": int(entry["bin"]),
                        "n": int(entry["n"]),
                        "mean_predicted": round(entry["mean_predicted"], DECIMALS),
                        "observed_rate": round(entry["observed_rate"], DECIMALS),
                        "probability_min": round(entry["probability_min"], DECIMALS),
                        "probability_max": round(entry["probability_max"], DECIMALS),
                    }
                )
    return {
        "disclosure": "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
        "model_key": selected,
        "rows": rows,
        "bins": bins,
    }


def referral_rows(run: Path, selected: str) -> tuple[list[dict], float]:
    """One published row per referral, plus the admission-window coverage the run used (constant per run)."""
    rows: list[dict] = []
    coverages: set[float] = set()
    with (run / "predictions.csv").open(encoding="utf-8", newline="") as fh:
        for source in csv.DictReader(fh):
            where = f"referral {source['referral_id']}"
            if source["selected_model"] != selected:
                raise SystemExit(f"{where}: row selects {source['selected_model']!r}, the run selected {selected!r}")
            level = source["aalen_johansen_level"]
            if level not in TIERS:
                raise SystemExit(f"{where}: unknown hierarchy level {level!r}")
            admitted = [probability(source[f"{selected}__hospitalized__{h}d"], where) for h in HORIZONS]
            if admitted != sorted(admitted):
                raise SystemExit(f"{where}: admission probability falls as the horizon grows")
            refused = probability(source[f"{selected}__refused__30d"], where)
            lower, upper = source["admission_interval_lower_days"], source["admission_interval_upper_days"]
            coverages.add(float(source["admission_interval_coverage"]))
            rows.append(
                {
                    "referral_id": int(source["referral_id"]),
                    "org_code": source["org_code"],
                    "profile_code": source["profile_code"],
                    "estimate_tier": TIERS[level],
                    "similar_training_rows": int(source["similar_training_rows"]),
                    "admitted_7d": admitted[0],
                    "admitted_14d": admitted[1],
                    "admitted_30d": admitted[2],
                    "refused_30d": refused,
                    "window_lower_days": None if lower == "" else round(float(lower), 1),
                    "window_upper_days": None if upper == "" else round(float(upper), 1),
                    "abstention_reason": NO_WINDOW if lower == "" else None,
                    "refusal_attention": False,  # filled once the cohort-wide threshold is known
                    "degenerate_30d": degenerate(admitted[2], refused),
                }
            )
    if len(coverages) != 1:
        raise SystemExit("the run recorded more than one admission-interval coverage")
    rows.sort(key=lambda row: row["referral_id"])
    return rows, coverages.pop()


def apply_attention(rows: list[dict]) -> dict:
    """Fix the follow-up threshold at the cohort's upper decile and flag every row at or above it."""
    risks = sorted(row["refused_30d"] for row in rows)
    threshold = round(risks[min(len(risks) - 1, int(ATTENTION_QUANTILE * len(risks)))], DECIMALS)
    flagged = 0
    for row in rows:
        row["refusal_attention"] = row["refused_30d"] >= threshold
        flagged += row["refusal_attention"]
    return {
        "metric": "refused_30d",
        "quantile": ATTENTION_QUANTILE,
        "threshold": threshold,
        "definition": ATTENTION_DEFINITION,
        "intended_use": ATTENTION_USE,
        "flagged_count": flagged,
    }


def degenerate(admitted_30d: float, refused_30d: float) -> bool:
    """True when the 30-day distribution puts everything on one outcome: admitted, refused, or still waiting."""
    return max(admitted_30d, refused_30d, round(1.0 - admitted_30d - refused_30d, DECIMALS)) >= 1 - 1e-6


def degeneracy_block(rows: list[dict]) -> dict:
    by_outcome: dict[str, int] = {}
    for row in rows:
        if not row["degenerate_30d"]:
            continue
        if row["admitted_30d"] >= 1 - 1e-6:
            outcome = "admitted"
        elif row["refused_30d"] >= 1 - 1e-6:
            outcome = "refused"
        else:
            outcome = "still_waiting"
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
    return {
        "definition": DEGENERACY_DEFINITION,
        "count": sum(by_outcome.values()),
        "by_outcome": by_outcome,
    }


def counted(rows: list[dict], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row[key]
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return counts


def build(run: Path, publication_id: str, source_code_commit: str) -> tuple[dict, dict]:
    config = read_json(run, "config.json")
    decision = read_json(run, "decision.json")
    metrics = read_json(run, "metrics.json")
    manifest = read_json(run, "manifest.json")
    run_info = read_json(run, "run.json")
    selected = decision["selected_model"]
    if tuple(config["horizons"]) != HORIZONS:
        raise SystemExit(f"{run}: the run does not carry the horizons {HORIZONS}")

    rows, coverage = referral_rows(run, selected)
    if not rows:
        raise SystemExit(f"{run}: predictions.csv holds no referral; refusing to publish an empty estimate set")
    attention = apply_attention(rows)

    payload = {
        "schema_version": "referral_estimates_v1",
        "contract_version": "1.0.0",
        "publication_id": publication_id,
        "publication_identity_sha256": "0" * 64,
        "source_code_commit": source_code_commit,
        "origin": config["origin"],
        "outcome_cutoff": config["outcome_cutoff"],
        "horizons": list(HORIZONS),
        "admission_window_coverage": coverage,
        "source_run": {
            "run_id": run.name,
            "artifact_identity_sha256": manifest["artifact_identity_sha256"],
            "scientific_identity_sha256": manifest["scientific_identity_sha256"],
            "training_sha256": run_info["training_sha256"],
            "scoring_sha256": run_info["scoring_sha256"],
            "seed": run_info["seed"],
            "library_versions": run_info["library_versions"],
        },
        "selection": selection_block(decision, metrics),
        "calibration": calibration_block(metrics, selected, len(rows)),
        "estimate_tiers": counted(rows, "estimate_tier"),
        "abstention_counts": counted(rows, "abstention_reason"),
        "degeneracy": degeneracy_block(rows),
        "attention": attention,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "limitations": LIMITATIONS,
        "referrals": rows,
    }
    bundle = ReferralEstimatesBundle.model_validate(payload)
    payload = bundle.model_dump(mode="json")
    payload["publication_identity_sha256"] = identity_of(bundle)

    report = {
        "publication_id": publication_id,
        "origin": config["origin"],
        "source_run": run.name,
        "selected_model": selected,
        "fallback_used": bool(decision["fallback_used"]),
        "referral_count": len(rows),
        "estimate_tiers": payload["estimate_tiers"],
        "abstention_counts": payload["abstention_counts"],
        "degenerate": payload["degeneracy"],
        "attention_threshold": attention["threshold"],
        "attention_flagged": attention["flagged_count"],
        "hospitals": len({row["org_code"] for row in rows}),
        "profiles": len({row["profile_code"] for row in rows}),
    }
    return payload, report


def write_outputs(output: Path, files: list[tuple[str, dict]]) -> None:
    """Immutable outputs: an existing file must already hold exactly these bytes."""
    output.mkdir(parents=True, exist_ok=True)
    for name, value in files:
        path = output / name
        data = canonical(value) + b"\n"
        if path.exists():
            if path.read_bytes() != data:
                raise SystemExit(f"immutable output already exists with different content: {name}")
        else:
            temporary = path.with_suffix(".json.partial")
            temporary.write_bytes(data)
            temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root holding artifacts/")
    parser.add_argument("--run", type=Path, default=None, help=f"origin_journey run directory (default {RUN_DIR})")
    parser.add_argument("--publication-id", default=PUBLICATION, help=f"publication id (default {PUBLICATION})")
    parser.add_argument("--source-code-commit", default=None, help="commit of the producing code (default: HEAD)")
    parser.add_argument("--out", type=Path, help=f"output directory (default {OUTPUT_DIR}/<publication-id>)")
    args = parser.parse_args()

    run = (args.run or args.root / RUN_DIR).resolve()
    if not run.is_dir():
        raise SystemExit(f"{run}: no such origin_journey run directory")
    commit = args.source_code_commit or head_commit(args.root)
    payload, report = build(run, args.publication_id, commit)
    output = args.out or args.root / OUTPUT_DIR / args.publication_id
    write_outputs(output, [("referral_estimates.json", payload), ("build-report.json", report)])
    # the bytes that were written must publish: parse them back through the same path the API uses
    parsed = parse_bundle((output / "referral_estimates.json").read_bytes())
    print(
        json.dumps(
            {
                "output": str(output),
                **report,
                "bytes": (output / "referral_estimates.json").stat().st_size,
                "identity": parsed.bundle.publication_identity_sha256,
                "bundle_sha256": parsed.bundle_sha256,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
