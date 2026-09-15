"""Render reports/02_models.md from the metrics of the current registry versions."""

import datetime as dt
import json
from pathlib import Path

from hqai_ml.evaluation.feature_notes import LOAD_FEATURES, REFERRAL_FEATURES
from hqai_ml.ingest.config import IngestSettings
from hqai_ml.models.config import ModelConfig
from hqai_ml.registry import store

A_B3 = "B3 median hospital × profile (fallback B2)"
B_B3 = "B3 rate hospital × profile (fallback B2)"
LEVELS = ["hospital × profile (modelled)", "hospital × profile (fallback)", "region × profile"]


# ------------------------------------------------------------------ formatting
def f(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "**no**"
    if isinstance(v, int):
        return f"{v:,}".replace(",", " ")
    if isinstance(v, float):
        return f"{v:,.{nd}f}".replace(",", " ")
    return str(v).replace("|", "\\|")


def pct(v, nd=1):
    return "—" if v is None else f"{100 * v:.{nd}f}%"


def cut(s, n=48):
    s = "—" if s is None else str(s)
    return (s[: n - 1] + "…" if len(s) > n else s).replace("|", "\\|")


def table(header, rows):
    out = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" if i == 0 else "---:" for i in range(len(header))) + "|",
    ]
    return out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows] + [""]


def bold_min(values: list, fmt):
    finite = [v for v in values if v is not None]
    best = min(finite) if finite else None
    return [f"**{fmt(v)}**" if v is not None and v == best else fmt(v) for v in values]


def bold_max(values: list, fmt):
    finite = [v for v in values if v is not None]
    best = max(finite) if finite else None
    return [f"**{fmt(v)}**" if v is not None and v == best else fmt(v) for v in values]


def compare_table(rows: list[dict], columns: list[tuple]) -> list[str]:
    """Model-vs-baselines table; the best value of each column (min or max) is bold."""
    cells = []
    for _, key, better, fmt in columns:
        values = [r[key] for r in rows]
        cells.append(bold_min(values, fmt) if better == "min" else bold_max(values, fmt))
    return table(
        ["model"] + [c[0] for c in columns], [[r["model"]] + [col[i] for col in cells] for i, r in enumerate(rows)]
    )


def _load(settings: IngestSettings, name: str) -> dict | None:
    try:
        path = store.version_dir(settings.artifacts_dir, name)
    except FileNotFoundError:
        return None
    return {
        "version": path.name,
        "meta": store.load_json(path, "meta.json"),
        "metrics": store.load_json(path, "metrics.json"),
        "display": store.load_json(path, "display.json") if (path / "display.json").exists() else {},
    }


# ---------------------------------------------------------------------- sections
def section_data(cfg: ModelConfig, arts: dict, settings: IngestSettings) -> list[str]:
    manifest = json.loads((settings.processed_dir / "_manifest.json").read_text(encoding="utf-8"))
    s = cfg.split
    L = [
        "## 0. Data and split",
        "",
        f"Input: `data/processed` from ingest run {manifest['started_at']} (dataset 3 complete: "
        f"{'yes' if not manifest['sources']['dataset_3']['skipped'] else 'no'}).",
        "",
    ]
    rows = []
    if arts.get("wait_time"):
        p = arts["wait_time"]["metrics"]["population"]
        rows.append(
            ["A wait time", p["definition"], f(p["train_rows"]), f(p["test_rows"]), "wait_days (trained on log1p)"]
        )
    if arts.get("refusal_risk"):
        p = arts["refusal_risk"]["metrics"]["population"]
        rows.append(
            [
                "B refusal risk",
                p["definition"],
                f(p["train_rows"]),
                f(p["test_rows"]),
                f"refused (train rate {pct(p['train_refusal_rate'])}, test {pct(p['test_refusal_rate'])})",
            ]
        )
    if arts.get("load_forecast"):
        sc = arts["load_forecast"]["metrics"]["series"]
        rows.append(
            [
                "C load forecast",
                "daily series from agg_daily_hospital_profile / agg_daily_region_profile",
                f"{f(sc['hospital_profile_modelled'])} + {f(sc['region_profile'])} series",
                "3 rolling origins × 14 days",
                "daily registrations, daily hospitalizations",
            ]
        )
    L += table(["model", "population", "train", "test", "target"], rows)
    L += [
        f"- **Temporal split**: train on registrations {s.train_start} … {s.train_end}, test on {s.test_start} … "
        f"{s.test_end}. No random splits anywhere.",
        f"- Models A and B pick the number of boosting rounds by early stopping on the last "
        f"{cfg.early_stopping.holdout_days} days of the train period, then refit on the whole train period. "
        "LightGBM parameters are fixed defaults (`ml/configs/models.yaml`), no hyperparameter search.",
        "- **Labels are observed with hindsight**: outcomes of train-period referrals are known up to the data load "
        "(May 2026). A model retrained on 2025-03-01 in production would see long waits of February referrals as "
        "still open (censored). The evaluation therefore slightly flatters the models for long waits.",
        f"- Model C: rolling origins {', '.join(str(o) for o in cfg.load_forecast.backtest_origins)} (first forecast "
        "day; "
        "the model sees only days before it), 14 days each. The production model is refit on all days up to "
        f"{cfg.load_forecast.forecast_origin}.",
        "",
    ]
    return L


def section_features() -> list[str]:
    L = [
        "## 1. Features and leakage review",
        "",
        'd = registration date. "end of day d−1" means the value uses only events up to the day before registration.',
        "",
    ]
    L += table(
        ["feature", "used in", "known at", "note"], [[f"`{k}`", v[0], v[1], v[2]] for k, v in REFERRAL_FEATURES.items()]
    )
    L += ["Model C features (t = last known day, target = t + h):", ""]
    L += table(["features", "note"], [[f"`{k}`", v] for k, v in LOAD_FEATURES.items()])
    return L


def _examples(ex: list[dict], unit: str) -> list[str]:
    L = [
        "Each factor's effect is its SHAP value converted to "
        + ("days" if unit == "days" else "percentage points")
        + " with one common scale per referral, so all factors together add up exactly to "
        '"this prediction − the average prediction"; only the top 5 are shown (`ml/hqai_ml/explain/shap_explain.py`).',
        "",
    ]
    for e in ex:
        actual = (
            "—"
            if e["actual"] is None
            else (f"{e['actual']:.0f} days" if unit == "days" else ("refused" if e["actual"] else "hospitalized"))
        )
        pred = f"{e['prediction']:.1f} days" if unit == "days" else pct(e["prediction"])
        L += [
            f"**Referral {e['referral_id']}** (registered {e['registration_date']}, profile {e['profile_code']}, "
            f"hospital {e['org_code']}; prediction at the {int(e['quantile'] * 100)}th percentile) — predicted {pred}, "
            f"actual {actual}:",
            "",
        ]
        L += [f"- {x['text']}" for x in e["factors"]] + [""]
    return L


def _shap_table(shap: dict, unit: str) -> list[str]:
    L = [
        f"Mean |SHAP| on {f(shap['sample_size'])} test referrals, in model units ({unit}); additivity check "
        f"max |base + ΣSHAP − prediction| = {shap['additivity_max_abs_error']:.1e}.",
        "",
    ]
    return L + table(
        ["feature", "mean abs SHAP", "share"],
        [[f"`{r['feature']}`", f(r["mean_abs_shap"], 4), pct(r["share"])] for r in shap["importance"]],
    )


def section_wait(a: dict) -> list[str]:
    m, disp = a["metrics"], a["display"]
    L = [
        f"## 2. Model A — wait time (version {a['version']}, {m['best_iteration']} trees)",
        "",
        f"Population: {m['population']['definition']}. Median wait: train {m['population']['train_median_wait']:.0f} "
        "days, "
        f"test {m['population']['test_median_wait']:.0f} days.",
        "",
        "### 2.1 Test set, model vs baselines",
        "",
    ]
    L += compare_table(
        m["overall"],
        [
            ("MAE, days", "mae", "min", f),
            ("median AE", "median_ae", "min", f),
            ("WAPE", "wape", "min", pct),
            ("within ±7 days", "within_7d", "max", pct),
            ("Spearman", "spearman", "max", lambda v: f(v, 3)),
        ],
    )
    L += ["### 2.2 By patient region (test)", ""]
    L += table(
        [
            "region",
            "n",
            "median actual",
            "MAE model",
            "MAE B1",
            "MAE B2",
            "MAE B3",
            "WAPE model",
            "WAPE B3",
            "±7d model",
            "±7d B3",
            "Spearman model",
            "Spearman B3",
        ],
        [
            [
                cut(disp.get("region", {}).get(r["segment"], r["segment"]), 30),
                f(r["n"]),
                f(r["median_actual"], 0),
                *bold_min([r["mae_model"], r["mae_b1"], r["mae_b2"], r["mae_b3"]], f),
                pct(r["wape_model"]),
                pct(r["wape_b3"]),
                pct(r["within_7d_model"]),
                pct(r["within_7d_b3"]),
                f(r["spearman_model"], 3),
                f(r["spearman_b3"], 3),
            ]
            for r in m["by_region"]
        ],
    )
    L += ["### 2.3 By top-10 profiles (test volume)", ""]
    L += table(
        [
            "profile",
            "n",
            "median actual",
            "MAE model",
            "MAE B1",
            "MAE B2",
            "MAE B3",
            "WAPE model",
            "WAPE B3",
            "±7d model",
            "±7d B3",
            "Spearman model",
            "Spearman B3",
        ],
        [
            [
                cut(f"{r['segment']} {disp.get('profile', {}).get(r['segment'], '')}", 40),
                f(r["n"]),
                f(r["median_actual"], 0),
                *bold_min([r["mae_model"], r["mae_b1"], r["mae_b2"], r["mae_b3"]], f),
                pct(r["wape_model"]),
                pct(r["wape_b3"]),
                pct(r["within_7d_model"]),
                pct(r["within_7d_b3"]),
                f(r["spearman_model"], 3),
                f(r["spearman_b3"], 3),
            ]
            for r in m["by_profile"]
        ],
    )
    L += ["### 2.4 SHAP global importance", ""] + _shap_table(m["shap"], "log1p days")
    L += ["### 2.5 Ablation: the excluded `planned_lag_days`", ""]
    L += table(
        ["variant", "MAE, days", "median AE", "WAPE", "within ±7 days", "Spearman"],
        [
            [r["model"], f(r["mae"]), f(r["median_ae"]), pct(r["wape"]), pct(r["within_7d"]), f(r["spearman"], 3)]
            for r in m["ablation_planned_lag"]
        ],
    )
    L += [
        "The planned date on its own predicts the wait almost exactly. That is only possible if `planned_dt` is set "
        "or corrected once the admission is scheduled, so it is not a registration-time feature and stays excluded "
        "until the data owner confirms when it is filled.",
        "",
        "### 2.6 Example explanations",
        "",
    ]
    return L + _examples(m["examples"], "days")


def section_refusal(b: dict) -> list[str]:
    m, disp = b["metrics"], b["display"]
    L = [
        f"## 3. Model B — refusal risk (version {b['version']}, {m['best_iteration']} trees)",
        "",
        f"Population: {m['population']['definition']}. Refusal rate: train "
        f"{pct(m['population']['train_refusal_rate'])}, "
        f"test {pct(m['population']['test_refusal_rate'])}.",
        "",
        "### 3.1 Test set, model vs baselines",
        "",
        "`top 10%` = the 10% of test referrals with the highest predicted risk.",
        "",
    ]
    L += compare_table(
        m["overall"],
        [
            ("ROC-AUC", "roc_auc", "max", lambda v: f(v, 3)),
            ("PR-AUC", "pr_auc", "max", lambda v: f(v, 3)),
            ("Brier", "brier", "min", lambda v: f(v, 4)),
            ("precision top 10%", "precision_top", "max", pct),
            ("recall top 10%", "recall_top", "max", pct),
        ],
    )
    L += ["### 3.2 Calibration (10 equal-frequency bins of predicted probability, test)", ""]
    L += table(
        ["bin", "n", "predicted range", "mean predicted", "observed", "B3 mean predicted", "B3 observed"],
        [
            [
                c["bin"] + 1,
                f(c["n"]),
                f"{c['p_min']:.3f} – {c['p_max']:.3f}",
                pct(c["mean_pred"]),
                pct(c["observed"]),
                pct(c3["mean_pred"]),
                pct(c3["observed"]),
            ]
            for c, c3 in zip(m["calibration_model"], m["calibration_b3"], strict=True)
        ],
    )
    seg_header = [
        "n",
        "refusal rate",
        "mean predicted",
        "ROC-AUC model",
        "ROC-AUC B3",
        "PR-AUC model",
        "PR-AUC B3",
        "Brier model",
        "Brier B3",
    ]

    def seg_row(r):
        return [
            f(r["n"]),
            pct(r["refusal_rate"]),
            pct(r["mean_pred_model"]),
            *bold_max([r["roc_auc_model"], r["roc_auc_b3"]], lambda v: f(v, 3)),
            *bold_max([r["pr_auc_model"], r["pr_auc_b3"]], lambda v: f(v, 3)),
            *bold_min([r["brier_model"], r["brier_b3"]], lambda v: f(v, 4)),
        ]

    L += ["### 3.3 By patient region (test)", ""]
    L += table(
        ["region"] + seg_header,
        [[cut(disp.get("region", {}).get(r["segment"], r["segment"]), 30)] + seg_row(r) for r in m["by_region"]],
    )
    L += ["### 3.4 By top-10 profiles (test volume)", ""]
    L += table(
        ["profile"] + seg_header,
        [
            [cut(f"{r['segment']} {disp.get('profile', {}).get(r['segment'], '')}", 40)] + seg_row(r)
            for r in m["by_profile"]
        ],
    )
    L += ["### 3.5 SHAP global importance", ""] + _shap_table(m["shap"], "log-odds")
    L += ["### 3.6 Ablation: the excluded `planned_lag_days`", ""]
    L += table(
        ["variant", "ROC-AUC", "PR-AUC", "Brier", "precision top 10%", "recall top 10%"],
        [
            [
                r["model"],
                f(r["roc_auc"], 3),
                f(r["pr_auc"], 3),
                f(r["brier"], 4),
                pct(r["precision_top"]),
                pct(r["recall_top"]),
            ]
            for r in m["ablation_planned_lag"]
        ],
    )
    L += [
        "A missing planned date alone is a strong refusal signal — consistent with `planned_dt` being filled only when "
        "the hospital accepts the referral. Excluded for the same reason as in Model A.",
        "",
        "### 3.7 Example explanations",
        "",
    ]
    return L + _examples(m["examples"], "prob")


def _forecast_rows(rows, keys):
    out = []
    for r in rows:
        w = bold_min([r["wape_model"], r["wape_seasonal_naive"], r["wape_mean_28d"], r["wape_mean_7d"]], pct)
        out.append(
            [
                *(r[k] for k in keys),
                f(r["n"]),
                f(r["actual_total"], 0),
                *w,
                f(r["mae_model"]),
                f(r["mae_seasonal_naive"]),
            ]
        )
    return out


def section_load(c: dict, display: dict) -> list[str]:
    m = c["metrics"]
    sc = m["series"]
    hdr_tail = [
        "n",
        "actual total",
        "WAPE model",
        "WAPE seasonal naive",
        "WAPE mean 28d",
        "WAPE mean 7d",
        "MAE model",
        "MAE seasonal naive",
    ]
    L = [
        f"## 4. Model C — load forecast (version {c['version']})",
        "",
        f"Series: {f(sc['hospital_profile_modelled'])} of {f(sc['hospital_profile_total'])} hospital × profile "
        "series have "
        f"train-period mean registrations ≥ {sc['min_series_mean']:g}/day and are modelled individually; the other "
        f"{f(sc['hospital_profile_fallback'])} get their region × profile forecast × their train-period share of it. "
        f"All {f(sc['region_profile'])} region × profile series are modelled. One global LightGBM (Poisson) model "
        "per target.",
        "",
        "### 4.1 Does the model beat the seasonal-naive baseline? (pooled over 3 origins × 14 days)",
        "",
    ]
    L += table(
        [
            "target",
            "series level",
            "WAPE model",
            "WAPE seasonal naive",
            "WAPE mean 28d",
            "WAPE mean 7d",
            "beats seasonal naive",
            "beats all baselines",
            "origin × bucket cells beating seasonal naive",
        ],
        [
            [
                r["target"],
                r["eval_level"],
                *bold_min([r["wape_model"], r["wape_seasonal_naive"], r["wape_mean_28d"], r["wape_mean_7d"]], pct),
                f(r["beats_seasonal_naive"]),
                f(r["beats_all_baselines"]),
                f"{r['cells_beating_seasonal_naive']} / {r['cells']}",
            ]
            for r in m["beats_seasonal_naive"]
        ],
    )
    cmp = m.get("previous_version_comparison")
    if cmp:
        change = (
            "; ".join(
                [f"holidays added: {', '.join(cmp['holidays_added'])}"] * bool(cmp["holidays_added"])
                + [f"holidays removed: {', '.join(cmp['holidays_removed'])}"] * bool(cmp["holidays_removed"])
            )
            or "no holiday change"
        )
        cells = "; ".join(
            f"{r['target']} {r['eval_level']} {pct(r['wape_model_before'])} → {pct(r['wape_model_after'])}"
            for r in sorted(cmp["pooled"], key=lambda r: (r["target"], r["eval_level"]))
        )
        L += [
            f"**Change vs previous version `{cmp['previous_version']}` ({change}).** Pooled model WAPE before → "
            f"after: {cells}.",
            "",
        ]
    L += ["### 4.2 Backtest per origin", ""]
    for origin in m["backtest_origins"]:
        rows = [r for r in m["per_origin"] if r["origin"] == origin]
        L += [f"**Forecast origin {origin}** (model trained on days before it)", ""]
        L += table(
            ["target", "series level", "horizon"] + hdr_tail, _forecast_rows(rows, ["target", "eval_level", "bucket"])
        )
    L += ["### 4.3 Pooled over origins, by horizon bucket", ""]
    L += table(
        ["target", "series level", "horizon"] + hdr_tail,
        _forecast_rows(m["pooled_by_bucket"], ["target", "eval_level", "bucket"]),
    )
    L += ["### 4.4 By region (region × profile series, pooled)", ""]
    reg = display.get("region", {})
    rows = sorted(m["by_region"], key=lambda r: (r["target"], r["region_code"]))
    for r in rows:
        r["region"] = cut(reg.get(r["region_code"], r["region_code"]), 30)
    L += table(["target", "region"] + hdr_tail, _forecast_rows(rows, ["target", "region"]))
    L += [
        f"### 4.5 Top-{len({r['org_code'] for r in m['by_top_hospital']})} hospitals by train-period registrations "
        "(their individually modelled profile series, pooled)",
        "",
    ]
    org = display.get("org", {})
    rows = sorted(m["by_top_hospital"], key=lambda r: (r["target"], -r["train_registrations"]))
    for r in rows:
        r["hospital"] = cut(f"{r['org_code']} {org.get(r['org_code'], '')}", 45)
    L += table(["target", "hospital"] + hdr_tail, _forecast_rows(rows, ["target", "hospital"]))
    L += [
        "### 4.6 Derived queue forecast",
        "",
        "queue(t+h) = max(0, queue(t+h−1) + forecast registrations − forecast hospitalizations). Refusals are not "
        'forecast, so this path drifts upward. Compared against "queue stays at its last known value".',
        "",
    ]
    qrows = []
    for r in m["queue"]:
        qrows.append(
            [
                r["origin"],
                r["eval_level"],
                r["bucket"],
                f(r["n"]),
                *bold_min([r["wape_model"], r["wape_last_value"]], pct),
                pct(r.get("bias_model")),
                pct(r.get("bias_last_value")),
            ]
        )
    L += table(
        [
            "origin",
            "series level",
            "horizon",
            "n",
            "WAPE queue forecast",
            "WAPE last value",
            "bias queue forecast",
            "bias last value",
        ],
        qrows,
    )
    L += ["`bias` = Σ(forecast − actual) / Σactual; positive means the forecast queue is too long.", ""]
    if m.get("calendar_check"):
        L += [
            "### 4.6a Calendar check: test-period weekdays with near-zero volume",
            "",
            "National registrations below 20% of the median for the same weekday. Days without a holiday flag are "
            "missing from `load_forecast.holidays` in `ml/configs/models.yaml`, so the model forecasts them as "
            "normal days.",
            "",
        ]
        L += table(
            ["date", "weekday", "registrations", "weekday median", "holiday flag in config"],
            [
                [r["date"], r["weekday"], f(r["registrations"], 0), f(r["weekday_median"], 0), f(r["holiday_flag"])]
                for r in m["calendar_check"]
            ],
        )
    L += ["### 4.7 Feature importance (gain, production models)", ""]
    for tgt, imp in m["gain_importance"].items():
        total = sum(x["gain"] for x in imp) or 1
        L += [f"**{tgt}**", ""] + table(
            ["feature", "gain share"], [[f"`{x['feature']}`", pct(x["gain"] / total)] for x in imp[:10]]
        )
    return L


# ---------------------------------------------------------------- findings etc.
def section_findings(arts: dict) -> list[str]:
    L = ["## 5. Findings", ""]
    a, b, c = arts.get("wait_time"), arts.get("refusal_risk"), arts.get("load_forecast")
    if a:
        m = a["metrics"]
        ov = {r["model"]: r for r in m["overall"]}
        lg, b3 = ov["LightGBM"], ov[A_B3]
        reg = a["display"].get("region", {})
        worst = sorted(m["by_region"], key=lambda r: -r["mae_model"])[:3]
        lost = [reg.get(r["segment"], r["segment"]) for r in m["by_region"] if r["mae_model"] >= r["mae_b3"]]
        prof = a["display"].get("profile", {})
        hard_prof = sorted(m["by_profile"], key=lambda r: -r["mae_model"])[:3]
        top = [x["feature"] for x in m["shap"]["importance"][:4]]
        metric_dirs = {"mae": "min", "median_ae": "min", "wape": "min", "within_7d": "max", "spearman": "max"}
        not_best = [
            k
            for k, d in metric_dirs.items()
            if any(
                r[k] is not None and (r[k] < lg[k] if d == "min" else r[k] > lg[k])
                for r in m["overall"]
                if r["model"] != "LightGBM"
            )
        ]
        verdict = (
            "beats all three baselines on every metric"
            if not not_best
            else f"beats all three baselines on {', '.join(k for k in metric_dirs if k not in not_best)}, "
            f"but not on {', '.join(not_best)}"
        )
        L += [
            f"**Wait time (A).** The model {verdict}: MAE {lg['mae']:.1f} days vs "
            f"{b3['mae']:.1f} for the best baseline (hospital × profile median, "
            f"−{100 * (1 - lg['mae'] / b3['mae']):.0f}%), "
            f"Spearman {lg['spearman']:.2f} vs {b3['spearman']:.2f}. The gain is modest: most of what is predictable "
            "is "
            "*which hospital and profile* the referral goes to (top SHAP features: "
            f"{', '.join(f'`{t}`' for t in top)}), "
            "and the hospital × profile median already captures that. Recent hospital state (queue, rolling wait) adds "
            "ranking quality on top of it.",
            f"Errors are dominated by long waits: median absolute error is {lg['median_ae']:.1f} days, but MAE is "
            f"{lg['mae']:.1f}. Hardest regions by MAE: "
            + "; ".join(f"{reg.get(r['segment'], r['segment'])} ({r['mae_model']:.1f} days)" for r in worst)
            + ". Hardest profiles: "
            + "; ".join(f"{prof.get(r['segment'], r['segment'])} ({r['mae_model']:.1f})" for r in hard_prof)
            + ". "
            + (
                f"The model does not beat B3 on MAE in: {', '.join(lost)}."
                if lost
                else "It beats B3 on MAE in every region."
            ),
            "",
        ]
    if b:
        m = b["metrics"]
        ov = {r["model"]: r for r in m["overall"]}
        lg, b3 = ov["LightGBM"], ov[B_B3]
        gap = max(abs(x["mean_pred"] - x["observed"]) for x in m["calibration_model"])
        reg = b["display"].get("region", {})
        low = sorted([r for r in m["by_region"] if r["roc_auc_model"] is not None], key=lambda r: r["roc_auc_model"])[
            :3
        ]
        lost = [
            reg.get(r["segment"], r["segment"])
            for r in m["by_region"]
            if (r["roc_auc_model"] or 0) <= (r["roc_auc_b3"] or 0)
        ]
        L += [
            f"**Refusal risk (B).** ROC-AUC {lg['roc_auc']:.3f} vs {b3['roc_auc']:.3f} (B3), PR-AUC "
            f"{lg['pr_auc']:.3f} vs "
            f"{b3['pr_auc']:.3f}, Brier {lg['brier']:.4f} vs {b3['brier']:.4f}. In the top-10% risk group "
            f"{pct(lg['precision_top'])} of referrals are refused (base rate {pct(lg['base_rate'])}), capturing "
            f"{pct(lg['recall_top'])} of all refusals. Calibration is good: the largest gap between mean predicted "
            f"and observed rate in any decile is {100 * gap:.1f} percentage points.",
            "Weakest ranking by region: "
            + "; ".join(f"{reg.get(r['segment'], r['segment'])} (AUC {r['roc_auc_model']:.3f})" for r in low)
            + ". "
            + (
                f"The model does not beat B3 on ROC-AUC in: {', '.join(lost)}."
                if lost
                else "It beats B3 on ROC-AUC in every region."
            )
            + " As with waits, the hospital and its recent refusal rate carry most of the signal; the diagnosis "
            "(`icd3`) is the main patient-level driver.",
            "",
        ]
    if c:
        m = c["metrics"]
        lines = []
        for r in m["beats_seasonal_naive"]:
            verdict = "beats" if r["beats_seasonal_naive"] else "**does not beat**"
            lines.append(
                f"- {r['target']}, {r['eval_level']}: model {verdict} seasonal naive "
                f"(WAPE {pct(r['wape_model'])} vs {pct(r['wape_seasonal_naive'])}; mean 28d {pct(r['wape_mean_28d'])}, "
                f"mean 7d {pct(r['wape_mean_7d'])}; {r['cells_beating_seasonal_naive']}/{r['cells']} origin × bucket "
                "cells)."
            )
        q = m["queue"]
        q_wins = sum(r["wape_model"] < r["wape_last_value"] for r in q)
        biases = [r["bias_model"] for r in q if r.get("bias_model") is not None]
        strongest = {}
        for r in m["beats_seasonal_naive"]:
            b = min(
                ("seasonal naive", r["wape_seasonal_naive"]),
                ("mean 28d", r["wape_mean_28d"]),
                ("mean 7d", r["wape_mean_7d"]),
                key=lambda x: x[1],
            )
            strongest[r["eval_level"]] = b[0]
        strongest_names = sorted(set(strongest.values()))
        region_rows = [r for r in m["per_origin"] if r["eval_level"] == "region × profile"]
        worst_cell = max(region_rows, key=lambda r: r["wape_model"])
        calendar = m.get("calendar_check", [])
        holidays = c["meta"].get("holidays", [])

        def cell_days(r):
            first = dt.date.fromisoformat(r["origin"]) + dt.timedelta(days=0 if r["bucket"] == "1–7" else 7)
            return {str(first + dt.timedelta(days=i)) for i in range(7)}

        def calendar_note(r):
            days = [c for c in calendar if c["date"] in cell_days(r)]
            flagged = [c["date"] for c in days if c["holiday_flag"]]
            unflagged_days = [c["date"] for c in days if not c["holiday_flag"]]
            parts = []
            if flagged:
                seen = [h for h in holidays if h < r["origin"]]
                parts.append(
                    f"it contains the holiday days {', '.join(flagged)} (flagged, but the model trained for this "
                    f"origin has seen only {len(seen)} holiday days to learn their effect from)"
                )
            if unflagged_days:
                parts.append(
                    f"it contains {', '.join(unflagged_days)}, a non-working weekday missing from the holiday list"
                )
            return "; ".join(parts)

        unflagged_cells = []
        for c in calendar:
            if c["holiday_flag"]:
                continue
            # compare only 1–7 windows: every 8–14 window of the March origins contains some special day
            hit = [
                r
                for r in region_rows
                if c["date"] in cell_days(r) and r["target"] == "registrations" and r["bucket"] == "1–7"
            ]
            for r in hit:
                others = [
                    x["wape_model"]
                    for x in region_rows
                    if x["target"] == r["target"]
                    and x["bucket"] == r["bucket"]
                    and x["origin"] != r["origin"]
                    and not any(d["date"] in cell_days(x) for d in calendar)
                ]
                unflagged_cells.append((c["date"], r, min(others) if others else None))
        L += (
            ["**Load forecast (C).** Verdict against the seasonal-naive baseline (same weekday last week):", ""]
            + lines
            + [
                "",
                f"The strongest baseline at every series level is {', '.join(strongest_names)}: daily referral "
                "counts have a "
                "very strong weekday pattern (weekends are near zero), which flat 7- and 28-day means ignore. The "
                "model "
                "learns essentially the same thing (`same_weekday_last` and `target_weekday` carry most of the gain) "
                "and adds "
                "level information from the rolling means, which is why its margin over seasonal naive is small at "
                "region "
                "level and larger for the noisier hospital × profile series. Relative errors on hospital × profile "
                "series stay high for every method because the daily counts are small.",
                f"Holidays are the main failure mode. The worst region-level cell is origin {worst_cell['origin']}, "
                f"{worst_cell['target']}, horizon {worst_cell['bucket']} (WAPE {pct(worst_cell['wape_model'])})"
                + (f": {calendar_note(worst_cell)}." if calendar_note(worst_cell) else ".")
                + "".join(
                    f" Origin {r['origin']}, registrations, horizon {r['bucket']} contains {day}, a non-working "
                    "weekday "
                    f"missing from the configured holiday list (calendar check 4.6a): WAPE {pct(r['wape_model'])} vs "
                    f"{pct(best)} for the same horizon at an origin without special days. Adding transferred days "
                    "off to the "
                    "calendar is the cheapest improvement available."
                    for day, r, best in unflagged_cells
                ),
                f"The derived queue forecast is **worse than keeping the last known queue** in {len(q) - q_wins} of "
                f"{len(q)} "
                f"origin × level × horizon cells. It is biased upward in {sum(b > 0 for b in biases)} of "
                f"{len(biases)} cells "
                f"(bias {pct(min(biases))} to {pct(max(biases))}) "
                "because the formula subtracts only hospitalizations while refusals also leave the queue, and "
                "summing 14 "
                "noisy daily forecasts adds variance that a flat forecast does not have. As specified it should not "
                "be shown "
                "to users; forecasting refusals (or the net outflow directly) is needed first.",
                "",
            ]
        )
    return L


def section_limitations() -> list[str]:
    return [
        "## 6. Limitations",
        "",
        "- **Two months of training data** (registrations 2025-01-01 … 2025-02-28) and one test month; no seasonality, "
        "no year-over-year validation. Metrics can shift materially with more history.",
        "- **Left-censored history**: nothing before 2025-01-01 exists, so queue and hospitalization aggregates are "
        "under-counted in January (warm-up). `day_of_window` lets models discount it, but January rows are "
        "systematically different from production conditions.",
        "- **Hindsight labels** for train-period referrals (see section 0); a production retrain would face censored "
        "long waits.",
        "- **`planned_dt` excluded**: if the data owner confirms it is fixed at registration, it would dominate both "
        "referral models (ablations 2.5 and 3.6) and the product should simply show it.",
        "- **ERSB capacity features** come from a snapshot with an unknown period.",
        "- **Holidays**: the test month contains Nauryz (21–25 March) and the transferred day off 10 March (both in "
        "the "
        "holiday list); the training period contains only a handful of holiday days, so their effect is estimated "
        "from very few examples. The calendar must be maintained by hand, including transferred days off.",
        "- **Model C queue forecast ignores refusals**: it is biased upward and loses to a flat last-value forecast "
        "(section 4.6); it also inherits the queue under-count of the data layer.",
        "- **Forecasts are not reconciled across levels**: the sum of hospital × profile forecasts differs from the "
        "region × profile forecast (modelled hospital series are forecast independently).",
        "- **Associations, not causes**: SHAP explains the model, not the healthcare system. A factor like "
        '"hospital X" means referrals to X waited longer historically, not that X is the reason.',
        "- **Intended use**: prioritisation and monitoring with a human in the loop (see docs/model_card.md), never "
        "automated decisions about individual patients.",
        "",
    ]


def write_report(settings: IngestSettings, cfg: ModelConfig) -> Path:
    arts = {name: _load(settings, name) for name in ("wait_time", "refusal_risk", "load_forecast")}
    display = (arts.get("wait_time") or arts.get("refusal_risk") or {}).get("display", {})
    versions = ", ".join(f"{k} `{v['version']}`" for k, v in arts.items() if v) or "none"
    L = [
        "# Models — wait time, refusal risk, load forecast",
        "",
        f"Generated {dt.datetime.now():%Y-%m-%d %H:%M} by `ml/pipelines/train.py` from the current registry versions: "
        f"{versions}. Artifacts: `artifacts/models/`.",
        "",
    ]
    L += section_data(cfg, arts, settings) + section_features()
    L += section_wait(arts["wait_time"]) if arts["wait_time"] else ["## 2. Model A — not trained", ""]
    L += section_refusal(arts["refusal_risk"]) if arts["refusal_risk"] else ["## 3. Model B — not trained", ""]
    L += section_load(arts["load_forecast"], display) if arts["load_forecast"] else ["## 4. Model C — not trained", ""]
    L += section_findings(arts) + section_limitations()
    out = settings.reports_dir / "02_models.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    return out
