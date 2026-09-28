#!/usr/bin/env python3
"""Offline publication of the verification worklist from the ML side's ghost-queue bundle; never imported by the API.

  make verification-worklist-bundle   -> artifacts/verification_worklist/<publication-id>/verification_worklist.json

The ML bundle is read, never recomputed: the order (`verification_rank`), the priority score, the probabilities,
the history-quality warnings and the per-area counts all come from it. The source is the final B5.1 bundle
(`ghost-queue-2025-03-17-v2`, schema 2), pinned by its publication identity and its compressed-file SHA-256: a
different file, or an older schema, stops the build rather than publishing from it.

What this tool adds is the product's framing, published as data rather than as UI copy:

* **the order** a bureau works through — the whole formal queue, ranked; nothing is selected out of the queue;
* **the history-quality mark** with the source's own reason codes, so "мало сопоставимой истории" on a screen is
  checkable rather than a vibe;
* **the earlier binary rule**, for comparison only, with the count it would have selected;
* **the yield curve** — of the first N in this order, how many turned out to be no longer current, against the
  whole queue's base rate. That is hindsight, computed by joining the order to the already-published waiting list,
  whose per-referral outcome field is the product's one source of "what actually happened". It carries the
  disclosure marker, names the publication it read, and feeds nothing; no row carries an outcome.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.schemas.verification_worklist import VerificationWorklistBundle  # noqa: E402
from app.services.verification_worklist import identity_of, parse_bundle  # noqa: E402

SOURCE = "artifacts/origin_journey/ghost-queue-2025-03-17-v2.json.gz"
# the final B5.1 publication; the default build refuses any other bytes
SOURCE_IDENTITY_SHA256 = "b34c69702936dc7afe6f3781dbb028d2d4c743eb97c0234ba820e07940f6daaa"
SOURCE_FILE_SHA256 = "219c4116e5e2c7e965123e12b456024bcd397fbb5a661924301d152ffde33edf"
SOURCE_SCHEMA = 2
WAITING_LIST = "artifacts/waiting_list/waiting-list-origin-2025-03-17-v1/waiting_list.json"
PUBLICATION = "verification-worklist-origin-2025-03-17-v2"
OUTPUT_DIR = "artifacts/verification_worklist"
DECIMALS = 6
# the top-N cutoffs the ML side fixed before its evaluation; the legacy rule's own count is appended as the last point
YIELD_POINTS = (500, 1000, 2000, 5000)

NOT_A_DECISION = {
    "ru": (
        "Это список на сверку, а не решение. Ни одно направление не снимается с очереди автоматически: "
        "решение принимает специалист."
    ),
    "kk": (
        "Бұл — тексеруге арналған тізім, шешім емес. Бірде-бір жолдама кезектен автоматты түрде алынбайды: "
        "шешімді маман қабылдайды."
    ),
}
RANKING_DEFINITION = {
    "ru": (
        "Порядок сверки задаёт оценка приоритета от 0 до 1: чем она выше, тем раньше стоит сверить запись. Она "
        "выше, когда вероятность госпитализации в ближайшие 90 дней низкая и направление ждёт уже {maturity} дней "
        "и больше, и ниже, когда сопоставимых направлений в истории меньше {support}. При равной оценке — кто ждёт "
        "дольше. Это порядок работы, а не вердикт о направлении."
    ),
    "kk": (
        "Тексеру ретін 0-ден 1-ге дейінгі басымдық бағасы анықтайды: ол неғұрлым жоғары болса, жазбаны соғұрлым "
        "ертерек тексерген жөн. Алдағы 90 күнде госпитализация ықтималдығы төмен болып, жолдама {maturity} күн және "
        "одан көп күтсе, баға жоғары; тарихта салыстырмалы жолдамалар {support}-ден аз болса, төмен. Баға тең "
        "болса — ұзағырақ күткені бірінші. Бұл — жұмыс реті, жолдама туралы үкім емес."
    ),
}
LEGACY_STATEMENT = {
    "ru": (
        "Прежнее правило — ждёт не меньше {days} дней и вероятность госпитализации в ближайшие {horizon} дней ниже "
        "{threshold} — отобрало бы {count} направлений. Оно оставлено только для сравнения: список им не отбирается "
        "и не упорядочивается."
    ),
    "kk": (
        "Бұрынғы ереже — кемінде {days} күн күтіп тұр және алдағы {horizon} күнде госпитализация ықтималдығы "
        "{threshold} төмен — {count} жолдаманы іріктер еді. Ол тек салыстыру үшін қалдырылды: тізім ол арқылы "
        "іріктелмейді және реттелмейді."
    ),
}
HISTORY_QUALITY_DEFINITION = {
    "ru": (
        "Мало сопоставимой истории: за оценкой меньше {support} сопоставимых направлений, ещё остававшихся под "
        "наблюдением, или в сопоставимой истории после такого срока ожидания не было ни одной госпитализации. "
        "Низкая вероятность здесь означает нехватку наблюдений, а не уверенность модели."
    ),
    "kk": (
        "Салыстырмалы тарих аз: бағаның артында әлі бақылауда болған {support}-ден аз салыстырмалы жолдама бар, не "
        "болмаса осындай күту мерзімінен кейін салыстырмалы тарихта бірде-бір госпитализация болмаған. Мұндағы "
        "төмен ықтималдық бақылаулардың жетіспеуін білдіреді, модельдің сенімділігін емес."
    ),
}
YIELD_DEFINITION = {
    "ru": (
        "Ретроспектива: если бы бюро сверяло записи в этом порядке, столько из первых N к дате отсечения источника "
        "так и не привели к госпитализации (отказ или всё ещё ждут). Для сравнения — та же доля по всей очереди. "
        "Это проверка порядка постфактум, она ни на что не влияет."
    ),
    "kk": (
        "Ретроспектива: бюро жазбаларды осы ретпен тексерсе, алғашқы N жолдаманың сонша бөлігі дереккөздің кесінді "
        "күніне дейін госпитализацияға әкелмеген (бас тарту немесе әлі күтуде). Салыстыру үшін — бүкіл кезектегі "
        "сол үлес. Бұл — ретті кейін тексеру, ол ештеңеге әсер етпейді."
    ),
}
LIMITATIONS = [
    "Список на сверку — это не очередь: измеренная очередь не меняется, не сокращается и публикуется отдельно.",
    "Оценка приоритета упорядочивает сверку и не классифицирует направления: она не говорит, что запись неактуальна.",
    "Признак говорит, что запись стоит сверить, и ничего не говорит о пациенте.",
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


def read_source(path: Path) -> tuple[dict, str]:
    raw = path.read_bytes()
    try:
        payload = json.loads(gzip.decompress(raw))
    except (OSError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path}: cannot read the ghost-queue artifact: {exc}") from exc
    version = payload.get("schema_version")
    if version != SOURCE_SCHEMA:
        raise SystemExit(f"{path}: schema_version {version!r}; this tool reads only the final schema {SOURCE_SCHEMA}")
    for key in (
        "publication_id",
        "publication_identity_sha256",
        "origin",
        "ranking",
        "audited_legacy_rule",
        "history_quality",
        "headline",
        "referrals",
        "aggregates",
    ):
        if key not in payload:
            raise SystemExit(f"{path}: the artifact lacks {key!r}")
    return payload, hashlib.sha256(raw).hexdigest()


def require_pinned(source: dict, file_sha256: str) -> None:
    """The default build publishes from the final B5.1 bytes or not at all."""
    if source["publication_identity_sha256"] != SOURCE_IDENTITY_SHA256 or file_sha256 != SOURCE_FILE_SHA256:
        raise SystemExit(
            f"the source is not the pinned B5.1 publication: identity {source['publication_identity_sha256'][:12]}…, "
            f"file {file_sha256[:12]}… (expected {SOURCE_IDENTITY_SHA256[:12]}…, {SOURCE_FILE_SHA256[:12]}…)"
        )


def probability(value: object, where: str) -> float:
    number = round(float(value), DECIMALS)
    if not 0.0 <= number <= 1.0:
        raise SystemExit(f"{where}: probability {number} lies outside [0, 1]")
    return number


def ranked_items(source: dict) -> list[dict]:
    """Every referral of the formal queue, in the source's own published order. Nothing is re-ranked here."""
    rows = sorted(source["referrals"], key=lambda row: int(row["verification_rank"]))
    if [int(row["verification_rank"]) for row in rows] != list(range(1, len(rows) + 1)):
        raise SystemExit("the source's verification_rank is not a dense 1..n order")
    items = []
    for row in rows:
        where = f"referral {row['referral_id']}"
        items.append(
            {
                "referral_id": int(row["referral_id"]),
                "rank": int(row["verification_rank"]),
                "org_code": row["org_code"],
                "region_code": row["hospital_region_code"],
                "profile_code": row["profile_code"],
                "days_waited_at_origin": int(row["days_waited_at_origin"]),
                "probability_admitted_30d": probability(row["probability_admitted_within_30d"], where),
                "probability_admitted_horizon": probability(row["probability_admitted_within_90d"], where),
                "probability_ever_admitted": probability(
                    row["probability_ever_admitted_within_observable_curve"], where
                ),
                "observable_curve_end_day": round(float(row["observable_curve_end_day"]), 1),
                "estimate_tier": row["estimate_tier"],
                "verification_priority_score": probability(row["verification_priority_score"], where),
                "comparable_training_at_risk_rows": int(row["comparable_training_at_risk_rows"]),
                "history_quality_warning": bool(row["history_quality_warning"]),
                "history_quality_reason_code": row["history_quality_reason_code"],
            }
        )
    return items


def area_rows(source: dict) -> list[dict]:
    def build(level: str, rows: list[dict], code_key: str) -> list[dict]:
        return [
            {
                "level": level,
                "code": row[code_key],
                "region_code": None,
                "formal_queue_count": int(row["formal_queue_count"]),
                "history_quality_warning_count": int(row["history_quality_warning_count"]),
                "history_quality_warning_share": round(float(row["history_quality_warning_share"]), DECIMALS),
            }
            for row in rows
        ]

    aggregates = source["aggregates"]
    regions = build("region", aggregates["by_region"], "hospital_region_code")
    hospitals = build("hospital", aggregates["by_hospital"], "org_code")
    by_org = {row["org_code"]: row["hospital_region_code"] for row in source["referrals"]}
    for row in hospitals:
        row["region_code"] = by_org[row["code"]]
    return sorted(regions + hospitals, key=lambda row: (row["level"], row["code"]))


def legacy_selected(source: dict) -> int:
    """How many referrals the earlier rule would select, on the source's unrounded probabilities."""
    rule = source["audited_legacy_rule"]
    return sum(
        int(row["days_waited_at_origin"]) >= int(rule["minimum_days_waited"])
        and float(row["probability_admitted_within_90d"]) < float(rule["admission_probability_strictly_below"])
        for row in source["referrals"]
    )


def yield_curve(items: list[dict], waiting_list: Path, legacy_count: int) -> dict:
    """Hindsight: join the order to the published waiting list and count what was never admitted."""
    try:
        published = json.loads(waiting_list.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"{waiting_list}: the waiting-list publication is needed for the yield curve: {exc}") from exc
    status = {row["referral_id"]: row["observed_after_origin"]["status"] for row in published["referrals"]}
    if set(status) != {item["referral_id"] for item in items}:
        raise SystemExit("the ranked order and the waiting-list publication do not hold the same referrals")
    # "no longer current" is the source's own definition of a ghost: no admission before the exclusive cutoff
    running = []
    found = 0
    for item in items:
        found += status[item["referral_id"]] != "ADMITTED"
        running.append(found)
    base_share = found / len(items)
    points = []
    for checked in sorted({*YIELD_POINTS, legacy_count}):
        if checked > len(items):
            continue
        hits = running[checked - 1]
        share = hits / checked
        points.append(
            {
                "checked": checked,
                "no_longer_current": hits,
                "share": round(share, DECIMALS),
                "lift": round(share / base_share, DECIMALS) if base_share else 0.0,
            }
        )
    return {
        "disclosure": "HINDSIGHT_NOT_AVAILABLE_AT_ORIGIN",
        "definition": YIELD_DEFINITION,
        "outcome_source": published["publication_id"],
        "outcome_source_identity_sha256": published["publication_identity_sha256"],
        "base": {"evaluated": len(items), "no_longer_current": found, "share": round(base_share, DECIMALS)},
        "points": points,
    }


def build(source_path: Path, waiting_list: Path, publication_id: str, source_code_commit: str) -> tuple[dict, dict]:
    source, file_sha256 = read_source(source_path)
    ranking = source["ranking"]
    legacy = source["audited_legacy_rule"]
    maturity = int(ranking["wait_maturity_days"])
    support = int(ranking["minimum_comparable_at_risk_rows"])
    horizon = int(legacy["admission_probability_horizon_days"])
    threshold = float(legacy["admission_probability_strictly_below"])
    items = ranked_items(source)
    areas = area_rows(source)
    headline = source["headline"]
    selected = legacy_selected(source)

    payload = {
        "schema_version": "verification_worklist_v2",
        "contract_version": "2.0.0",
        "publication_id": publication_id,
        "publication_identity_sha256": "0" * 64,
        "source_code_commit": source_code_commit,
        "origin": source["origin"],
        "decision_owner": "SPECIALIST_DECIDES",
        "not_a_decision": NOT_A_DECISION,
        "source_publication": {
            "publication_id": source["publication_id"],
            "publication_identity_sha256": source["publication_identity_sha256"],
            "file_sha256": file_sha256,
            "schema_version": int(source["schema_version"]),
            "model": source["model"],
        },
        "ranking": {
            "definition": {
                language: text.format(maturity=maturity, support=support)
                for language, text in RANKING_DEFINITION.items()
            },
            "keys": [f"{ranking['score_name']} desc", *ranking["tie_breakers"]],
            "score_name": ranking["score_name"],
            "score_formula": ranking["score_formula"],
            "wait_maturity_days": maturity,
            "minimum_comparable_at_risk_rows": support,
            "training_only_justification": ranking["training_only_justification"],
        },
        "legacy_rule": {
            "role": "AUDITED_REFERENCE_ONLY",
            "reason_code": legacy["reason_code"],
            "minimum_days_waited": int(legacy["minimum_days_waited"]),
            "horizon_days": horizon,
            "probability_strictly_below": threshold,
            "selected_count": selected,
            "training_only_justification": legacy["training_only_justification"],
            "statement": {
                language: text.format(
                    days=int(legacy["minimum_days_waited"]),
                    horizon=horizon,
                    threshold=f"{threshold:.0%}",
                    count=f"{selected:,}".replace(",", " "),
                )
                for language, text in LEGACY_STATEMENT.items()
            },
        },
        "history_quality": {
            "definition": {
                language: text.format(support=support) for language, text in HISTORY_QUALITY_DEFINITION.items()
            },
            "warning_count": int(headline["history_quality_warning_count"]),
            "warning_share": round(float(headline["history_quality_warning_share"]), DECIMALS),
            "reason_counts": {
                key: int(value) for key, value in source["history_quality"]["warning_reason_counts"].items()
            },
        },
        "estimands": source["estimands"],
        "counts": {
            "formal_queue_count": int(headline["formal_queue_count"]),
            "ranked_count": int(headline["ranked_verification_worklist_count"]),
        },
        "yield_curve": yield_curve(items, waiting_list, selected),
        "areas": areas,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "limitations": [*LIMITATIONS, *source.get("limitations", [])],
        "items": items,
    }
    bundle = VerificationWorklistBundle.model_validate(payload)
    payload = bundle.model_dump(mode="json")
    payload["publication_identity_sha256"] = identity_of(bundle)

    curve = payload["yield_curve"]
    report = {
        "publication_id": publication_id,
        "origin": source["origin"],
        "source_publication": source["publication_id"],
        "source_identity_sha256": source["publication_identity_sha256"],
        "source_file_sha256": file_sha256,
        "formal_queue_count": payload["counts"]["formal_queue_count"],
        "ranked_count": payload["counts"]["ranked_count"],
        "history_quality": payload["history_quality"]["reason_counts"],
        "history_quality_warning_count": payload["history_quality"]["warning_count"],
        "legacy_rule_selected": selected,
        "regions": sum(1 for row in areas if row["level"] == "region"),
        "hospitals": sum(1 for row in areas if row["level"] == "hospital"),
        "yield_base": curve["base"],
        "yield": {
            point["checked"]: [point["no_longer_current"], point["share"], point["lift"]] for point in curve["points"]
        },
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
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help=f"ghost-queue artifact (default {SOURCE}); must be the pinned B5.1 bytes",
    )
    parser.add_argument("--waiting-list", type=Path, default=None, help="published waiting list, for the yield curve")
    parser.add_argument("--publication-id", default=PUBLICATION, help=f"publication id (default {PUBLICATION})")
    parser.add_argument("--source-code-commit", default=None, help="commit of the producing code (default: HEAD)")
    parser.add_argument("--out", type=Path, help=f"output directory (default {OUTPUT_DIR}/<publication-id>)")
    args = parser.parse_args()

    source = args.source or args.root / SOURCE
    require_pinned(*read_source(source))
    waiting_list = args.waiting_list or args.root / WAITING_LIST
    commit = args.source_code_commit or head_commit(args.root)
    payload, report = build(source, waiting_list, args.publication_id, commit)
    output = args.out or args.root / OUTPUT_DIR / args.publication_id
    write_outputs(output, [("verification_worklist.json", payload), ("build-report.json", report)])
    # the bytes that were written must publish: parse them back through the same path the API uses
    parsed = parse_bundle((output / "verification_worklist.json").read_bytes())
    print(
        json.dumps(
            {
                "output": str(output),
                "source": str(source),
                **report,
                "bytes": (output / "verification_worklist.json").stat().st_size,
                "identity": parsed.bundle.publication_identity_sha256,
                "bundle_sha256": parsed.bundle_sha256,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
