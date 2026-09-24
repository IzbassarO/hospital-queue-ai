"""Database tables. Data layer: filled by ml/pipelines/ingest.py (docs/data.md).
Predictions and model registry: filled by ml/pipelines/predict.py (docs/model_card.md).
Serving marts: filled by ml/pipelines/build_marts.py (docs/api.md). decision_log: written by the API.

Column names here must match the Parquet files written by hqai_ml.ingest
(the loader COPYs by column name).
"""

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ------------------------------------------------------------------ dictionaries
class DimRegion(Base):
    __tablename__ = "dim_region"

    region_code: Mapped[str] = mapped_column(String(4), primary_key=True)
    region_name: Mapped[str] = mapped_column(Text)
    vote_region_name: Mapped[str | None] = mapped_column(Text)
    vote_share: Mapped[float | None] = mapped_column(Double)
    vote_referrals: Mapped[int | None] = mapped_column(Integer)
    runner_up_name: Mapped[str | None] = mapped_column(Text)
    runner_up_share: Mapped[float | None] = mapped_column(Double)
    is_ambiguous: Mapped[bool] = mapped_column(Boolean)
    manual_override: Mapped[bool] = mapped_column(Boolean)


class DimProfile(Base):
    __tablename__ = "dim_profile"

    profile_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    profile_name: Mapped[str | None] = mapped_column(Text)
    name_share: Mapped[float | None] = mapped_column(Double)
    n_referrals: Mapped[int] = mapped_column(Integer)
    is_day_hospital: Mapped[bool] = mapped_column(Boolean)


class DimIcd(Base):
    """ICD-10 code -> most frequent name spelling in the source systems (no official dictionary in the open data)."""

    __tablename__ = "dim_icd"

    icd10_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    icd10_name: Mapped[str] = mapped_column(Text)
    name_share: Mapped[float] = mapped_column(Double)  # share of named rows using this spelling
    n_referrals: Mapped[int] = mapped_column(Integer)


class ErsbSnapshot(Base):
    __tablename__ = "ersb_snapshot"

    ersb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    org_name: Mapped[str] = mapped_column(Text)
    org_key: Mapped[str] = mapped_column(Text, index=True)
    discharged_total: Mapped[int] = mapped_column(Integer)
    discharged_children: Mapped[int] = mapped_column(Integer)
    treated_budget: Mapped[int] = mapped_column(Integer)
    treated_paid: Mapped[int] = mapped_column(Integer)
    discharged_within_day: Mapped[int] = mapped_column(Integer)
    deaths_total: Mapped[int] = mapped_column(Integer)
    bed_days: Mapped[int] = mapped_column(Integer)
    amount_to_pay: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    avg_length_of_stay: Mapped[float | None] = mapped_column(Double)
    org_code: Mapped[str | None] = mapped_column(String(8), index=True)
    n_matched_org_codes: Mapped[int] = mapped_column(Integer)
    sdu_load_date: Mapped[dt.datetime | None] = mapped_column(DateTime)


class DimOrganization(Base):
    __tablename__ = "dim_organization"

    org_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    org_name: Mapped[str] = mapped_column(Text)
    org_key: Mapped[str] = mapped_column(Text, index=True)
    region_code: Mapped[str | None] = mapped_column(ForeignKey("dim_region.region_code"), index=True)
    region_method: Mapped[str | None] = mapped_column(String(32))
    n_referrals: Mapped[int] = mapped_column(Integer)
    n_origin_regions: Mapped[int] = mapped_column(Integer)
    ersb_id: Mapped[int | None] = mapped_column(ForeignKey("ersb_snapshot.ersb_id"))
    match_score: Mapped[float | None] = mapped_column(Double)
    match_method: Mapped[str | None] = mapped_column(String(16))


# ------------------------------------------------------------------------- facts
class FactReferral(Base):
    __tablename__ = "fact_referral"

    referral_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hospitalization_code: Mapped[str] = mapped_column(String(32), index=True)
    region_code: Mapped[str] = mapped_column(ForeignKey("dim_region.region_code"), index=True)
    org_code: Mapped[str] = mapped_column(ForeignKey("dim_organization.org_code"), index=True)
    profile_code: Mapped[str] = mapped_column(ForeignKey("dim_profile.profile_code"), index=True)
    seq_no: Mapped[str | None] = mapped_column(String(16))
    is_dup_code: Mapped[bool] = mapped_column(Boolean)
    hospital_region_code: Mapped[str | None] = mapped_column(String(4), index=True)
    referring_mo: Mapped[str | None] = mapped_column(Text)
    hospital_mo: Mapped[str | None] = mapped_column(Text)
    icd10_code: Mapped[str | None] = mapped_column(String(16))
    diagnosis_name: Mapped[str | None] = mapped_column(Text)
    bed_profile: Mapped[str | None] = mapped_column(Text)
    registration_dt: Mapped[dt.datetime] = mapped_column(DateTime)
    planned_dt_raw: Mapped[dt.datetime | None] = mapped_column(DateTime)
    planned_dt: Mapped[dt.datetime | None] = mapped_column(DateTime)
    polyclinic_dt: Mapped[dt.datetime | None] = mapped_column(DateTime)
    hospitalization_dt: Mapped[dt.datetime | None] = mapped_column(DateTime)
    refusal_dt: Mapped[dt.datetime | None] = mapped_column(DateTime)
    territorial_type: Mapped[str | None] = mapped_column(String(16))
    referral_purpose: Mapped[str | None] = mapped_column(Text)
    finance_source: Mapped[str | None] = mapped_column(Text)
    sdu_load_date: Mapped[dt.datetime | None] = mapped_column(DateTime)
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    outcome_conflict: Mapped[bool] = mapped_column(Boolean)
    registration_date: Mapped[dt.date] = mapped_column(Date, index=True)
    registration_weekday: Mapped[int] = mapped_column(SmallInteger)
    planned_week: Mapped[dt.date | None] = mapped_column(Date)
    hospitalization_date: Mapped[dt.date | None] = mapped_column(Date, index=True)
    refusal_date: Mapped[dt.date | None] = mapped_column(Date)
    resolution_date: Mapped[dt.date | None] = mapped_column(Date)
    wait_days: Mapped[int | None] = mapped_column(Integer)
    wait_to_refusal_days: Mapped[int | None] = mapped_column(Integer)
    same_day_registration: Mapped[bool] = mapped_column(Boolean)
    retro_registration: Mapped[bool] = mapped_column(Boolean)
    planned_dt_out_of_range: Mapped[bool] = mapped_column(Boolean)
    planned_lag_days: Mapped[int | None] = mapped_column(Integer)


class FactAdmissionRefusal(Base):
    __tablename__ = "fact_admission_refusal"

    refusal_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_part: Mapped[int] = mapped_column(SmallInteger)
    region_in: Mapped[str | None] = mapped_column(Text)
    region_code: Mapped[str | None] = mapped_column(ForeignKey("dim_region.region_code"), index=True)
    org_in: Mapped[str | None] = mapped_column(Text)
    org_code: Mapped[str | None] = mapped_column(ForeignKey("dim_organization.org_code"), index=True)
    org_match_method: Mapped[str | None] = mapped_column(String(16))
    resident: Mapped[str | None] = mapped_column(String(16))
    insured: Mapped[str | None] = mapped_column(String(32))
    benefit_cat: Mapped[str | None] = mapped_column(Text)
    refuse_dt: Mapped[dt.datetime] = mapped_column(DateTime)
    refuse_date: Mapped[dt.date] = mapped_column(Date, index=True)
    attach_region: Mapped[str | None] = mapped_column(Text)
    attach_region_code: Mapped[str | None] = mapped_column(String(4))
    attach_org: Mapped[str | None] = mapped_column(Text)
    icd10_code: Mapped[str | None] = mapped_column(String(16))
    icd_name: Mapped[str | None] = mapped_column(Text)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    finance_src: Mapped[str | None] = mapped_column(Text)
    sdu_load_date: Mapped[dt.datetime | None] = mapped_column(DateTime)


# -------------------------------------------------------------------- aggregates
class AggDailyHospitalProfile(Base):
    __tablename__ = "agg_daily_hospital_profile"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    org_code: Mapped[str] = mapped_column(String(8), primary_key=True, index=True)
    profile_code: Mapped[str] = mapped_column(String(8), primary_key=True, index=True)
    region_code: Mapped[str | None] = mapped_column(String(4), index=True)
    registrations: Mapped[int] = mapped_column(Integer)
    hospitalizations: Mapped[int] = mapped_column(Integer)
    refusals: Mapped[int] = mapped_column(Integer)
    queue_length: Mapped[int] = mapped_column(Integer)


class AggDailyRegionProfile(Base):
    __tablename__ = "agg_daily_region_profile"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    region_code: Mapped[str] = mapped_column(String(4), primary_key=True, index=True)
    profile_code: Mapped[str] = mapped_column(String(8), primary_key=True, index=True)
    registrations: Mapped[int] = mapped_column(Integer)
    hospitalizations: Mapped[int] = mapped_column(Integer)
    refusals: Mapped[int] = mapped_column(Integer)
    queue_length: Mapped[int] = mapped_column(Integer)


class AggDailyAdmissionRefusals(Base):
    __tablename__ = "agg_daily_admission_refusals"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    org_code: Mapped[str] = mapped_column(String(8), primary_key=True, index=True)
    region_code: Mapped[str | None] = mapped_column(String(4), index=True)
    refusals: Mapped[int] = mapped_column(Integer)


# ------------------------------------------------------------------- predictions
# Filled by ml/pipelines/predict.py (current model versions only; each run replaces the rows).
# pred_referral has no FK to fact_referral on purpose: `make ingest` truncates the facts, and
# referral_id is stable across ingests (deterministic ordering).
class PredReferral(Base):
    __tablename__ = "pred_referral"
    # the API lists referrals of one hospital × profile
    __table_args__ = (Index("ix_pred_referral_org_profile", "org_code", "profile_code"),)

    referral_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hospitalization_code: Mapped[str] = mapped_column(String(32), index=True)
    registration_date: Mapped[dt.date] = mapped_column(Date, index=True)
    org_code: Mapped[str] = mapped_column(String(8), index=True)
    profile_code: Mapped[str] = mapped_column(String(8), index=True)
    wait_model_version: Mapped[str] = mapped_column(String(32))
    refusal_model_version: Mapped[str] = mapped_column(String(32))
    pred_wait_days: Mapped[float] = mapped_column(Double)
    pred_refusal_prob: Mapped[float] = mapped_column(Double)
    explanation: Mapped[dict] = mapped_column(JSONB)  # {"wait_time": [top-5 factors], "refusal_risk": [top-5 factors]}
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class PredDailyForecast(Base):
    __tablename__ = "pred_daily_forecast"

    series_id: Mapped[str] = mapped_column(String(40), primary_key=True)  # hp:<org>:<profile> or rp:<region>:<profile>
    origin_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)  # last known day
    horizon: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    target_date: Mapped[dt.date] = mapped_column(Date, index=True)
    level: Mapped[str] = mapped_column(String(16))  # hospital | region
    org_code: Mapped[str | None] = mapped_column(String(8), index=True)
    region_code: Mapped[str] = mapped_column(String(4), index=True)
    profile_code: Mapped[str] = mapped_column(String(8), index=True)
    method: Mapped[str] = mapped_column(String(32))  # model | region_share_fallback
    pred_registrations: Mapped[float] = mapped_column(Double)
    pred_hospitalizations: Mapped[float] = mapped_column(Double)
    pred_queue: Mapped[float] = mapped_column(Double)
    model_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    trained_at: Mapped[dt.datetime] = mapped_column(DateTime)
    train_window: Mapped[dict] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB)  # headline metrics; full tables in artifacts/models/.../metrics.json
    is_current: Mapped[bool] = mapped_column(Boolean, index=True)
    artifact_path: Mapped[str] = mapped_column(Text)
    # Nullable for historical artifacts whose experiment provenance cannot be reconstructed.
    run_id: Mapped[str | None] = mapped_column(String(128))
    artifact_sha256: Mapped[str | None] = mapped_column(String(64))
    dataset_identity: Mapped[str | None] = mapped_column(String(64))
    config_identity: Mapped[str | None] = mapped_column(String(64))
    code_identity: Mapped[str | None] = mapped_column(String(64))
    evaluation_status: Mapped[str | None] = mapped_column(String(16))
    # title, intended_use, limitations, display names (artifact card.json <- ml/configs/model_cards.yaml)
    card: Mapped[dict | None] = mapped_column(JSONB)
    registered_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


# -------------------------------------------------------------- model assurance
# Published explicitly from a frozen, candidate-independent Model Assurance bundle. The backend
# owns this read model and never imports hqai_ml or reads ML artifacts at request time.
class ModelAssuranceSnapshot(Base):
    __tablename__ = "model_assurance_snapshot"
    __table_args__ = (
        UniqueConstraint("assurance_id", name="uq_model_assurance_snapshot_assurance_id"),
        UniqueConstraint("assurance_identity_sha256", name="uq_model_assurance_snapshot_identity"),
        Index(
            "ux_model_assurance_snapshot_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    assurance_id: Mapped[str] = mapped_column(String(128))
    contract_version: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(64))
    assurance_identity_sha256: Mapped[str] = mapped_column(String(64))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    source_code_commit: Mapped[str] = mapped_column(String(40))
    ml_freeze_status: Mapped[str] = mapped_column(String(64))
    product_contract_version: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), index=True)
    capability_count: Mapped[int] = mapped_column(Integer)
    failed_evidence_history: Mapped[list] = mapped_column(JSONB)
    claim_boundaries: Mapped[dict] = mapped_column(JSONB)
    monitoring_expectations: Mapped[list] = mapped_column(JSONB)
    freshness_policy: Mapped[dict] = mapped_column(JSONB)


class ModelAssuranceCapability(Base):
    __tablename__ = "model_assurance_capability"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "capability_id", name="uq_model_assurance_capability_snapshot_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("model_assurance_snapshot.id", ondelete="CASCADE"), index=True)
    capability_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str] = mapped_column(Text)
    evidence_status: Mapped[str] = mapped_column(String(16))
    acceptance_verdict: Mapped[str] = mapped_column(String(32))
    product_consumption_status: Mapped[str] = mapped_column(String(32))
    run_id: Mapped[str | None] = mapped_column(String(128))
    scientific_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    artifact_identity: Mapped[str | list | None] = mapped_column(JSONB)
    dataset_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    config_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    code_identity_sha256: Mapped[str | None] = mapped_column(String(64))
    model_identity: Mapped[str | list | None] = mapped_column(JSONB)
    estimand_id: Mapped[str | None] = mapped_column(Text)
    calibration_identity: Mapped[str | None] = mapped_column(Text)
    hierarchy_identity: Mapped[str | None] = mapped_column(Text)
    pressure_provider_identity: Mapped[str | None] = mapped_column(Text)
    prioritization_identity: Mapped[str | None] = mapped_column(Text)
    scenario_identity: Mapped[str | None] = mapped_column(Text)
    decision_alternative_identity: Mapped[str | None] = mapped_column(Text)
    human_review_required: Mapped[bool] = mapped_column(Boolean)
    autonomous_action: Mapped[bool] = mapped_column(Boolean)
    capacity_checked: Mapped[bool] = mapped_column(Boolean)
    causal_effect_claimed: Mapped[bool] = mapped_column(Boolean)
    serving_claim: Mapped[bool] = mapped_column(Boolean)
    physical_feasibility_status: Mapped[str] = mapped_column(String(32))
    promotion_status: Mapped[str] = mapped_column(String(32))
    freshness_state: Mapped[str] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSONB)


# ---------------------------------------------------- operational intelligence
# Explicitly published product projection of accepted flow evidence. Request-time code reads only
# these tables; source artifact locations are deliberately not part of the read model.
class OperationalIntelligenceSnapshot(Base):
    __tablename__ = "operational_intelligence_snapshot"
    __table_args__ = (
        UniqueConstraint("publication_id", name="uq_operational_intelligence_snapshot_publication_id"),
        UniqueConstraint(
            "publication_identity_sha256",
            name="uq_operational_intelligence_snapshot_identity",
        ),
        Index(
            "ux_operational_intelligence_snapshot_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    publication_id: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[str] = mapped_column(String(32))
    publication_identity_sha256: Mapped[str] = mapped_column(String(64))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    assurance_identity_sha256: Mapped[str] = mapped_column(String(64))
    source_code_commit: Mapped[str] = mapped_column(String(40))
    current_origin: Mapped[dt.date] = mapped_column(Date)
    freshness_state: Mapped[str] = mapped_column(String(16))
    publication_status: Mapped[str] = mapped_column(String(16))
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), index=True)
    forecast_count: Mapped[int] = mapped_column(Integer)
    signal_count: Mapped[int] = mapped_column(Integer)
    source_provenance: Mapped[dict] = mapped_column(JSONB)
    limitations: Mapped[list] = mapped_column(JSONB)


class OperationalForecast(Base):
    __tablename__ = "operational_forecast"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "series_id",
            "target",
            "origin",
            "target_date",
            name="uq_operational_forecast_point",
        ),
        Index(
            "ix_operational_forecast_scope",
            "snapshot_id",
            "origin",
            "level",
            "region_code",
            "org_code",
            "profile_code",
            "target",
            "target_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("operational_intelligence_snapshot.id", ondelete="CASCADE"), index=True
    )
    series_id: Mapped[str] = mapped_column(String(64))
    level: Mapped[str] = mapped_column(String(16))
    origin: Mapped[dt.date] = mapped_column(Date)
    target_date: Mapped[dt.date] = mapped_column(Date)
    horizon: Mapped[int] = mapped_column(SmallInteger)
    target: Mapped[str] = mapped_column(String(32))
    org_code: Mapped[str | None] = mapped_column(String(8))
    region_code: Mapped[str | None] = mapped_column(String(4))
    profile_code: Mapped[str | None] = mapped_column(String(8))
    central_value: Mapped[float] = mapped_column(Double)
    central_semantics: Mapped[str] = mapped_column(String(32))
    raw_p10: Mapped[float | None] = mapped_column(Double)
    raw_p50: Mapped[float | None] = mapped_column(Double)
    raw_p90: Mapped[float | None] = mapped_column(Double)
    calibrated_lower: Mapped[float | None] = mapped_column(Double)
    calibrated_upper: Mapped[float | None] = mapped_column(Double)
    calibration_nominal_coverage: Mapped[float | None] = mapped_column(Double)
    calibration_status: Mapped[str] = mapped_column(String(32))
    calibration_support_class: Mapped[str | None] = mapped_column(String(64))
    calibration_version: Mapped[str | None] = mapped_column(String(128))
    prediction_source: Mapped[str] = mapped_column(String(32))
    hierarchy_status: Mapped[str] = mapped_column(String(64))
    support_status: Mapped[str] = mapped_column(String(32))
    fallback_status: Mapped[str] = mapped_column(String(32))
    uncertainty_status: Mapped[str] = mapped_column(String(32))
    provenance_keys: Mapped[list] = mapped_column(JSONB)
    details: Mapped[dict] = mapped_column(JSONB)


class OperationalSignal(Base):
    __tablename__ = "operational_signal"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "signal_id", name="uq_operational_signal_snapshot_id"),
        Index("ix_operational_signal_order", "snapshot_id", "origin", "inbox_rank", "signal_id"),
        Index(
            "ix_operational_signal_scope",
            "snapshot_id",
            "region_code",
            "org_code",
            "profile_code",
            "target",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("operational_intelligence_snapshot.id", ondelete="CASCADE"), index=True
    )
    signal_id: Mapped[str] = mapped_column(String(128))
    signal_type: Mapped[str] = mapped_column(String(40))
    series_id: Mapped[str] = mapped_column(String(64))
    origin: Mapped[dt.date] = mapped_column(Date)
    target: Mapped[str] = mapped_column(String(32))
    org_code: Mapped[str | None] = mapped_column(String(8))
    region_code: Mapped[str | None] = mapped_column(String(4))
    profile_code: Mapped[str | None] = mapped_column(String(8))
    inbox_rank: Mapped[int | None] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(16))
    headline: Mapped[str] = mapped_column(Text)
    concise_reason: Mapped[str] = mapped_column(Text)
    materiality_status: Mapped[str | None] = mapped_column(String(64))
    support_status: Mapped[str] = mapped_column(String(32))
    fallback_status: Mapped[str] = mapped_column(String(32))
    uncertainty_status: Mapped[str] = mapped_column(String(32))
    pressure_basis: Mapped[str | None] = mapped_column(String(64))
    threshold_value: Mapped[float | None] = mapped_column(Double)
    threshold_status: Mapped[str | None] = mapped_column(String(32))
    forecast_value: Mapped[float | None] = mapped_column(Double)
    uncertainty_lower: Mapped[float | None] = mapped_column(Double)
    uncertainty_upper: Mapped[float | None] = mapped_column(Double)
    first_crossing_date: Mapped[dt.date | None] = mapped_column(Date)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    observed_anomaly_status: Mapped[str | None] = mapped_column(String(32))
    observed_anomaly_present: Mapped[bool] = mapped_column(Boolean)
    data_freshness: Mapped[dt.date | None] = mapped_column(Date)
    reason_codes: Mapped[list] = mapped_column(JSONB)
    evidence_facts: Mapped[list] = mapped_column(JSONB)
    provenance_keys: Mapped[list] = mapped_column(JSONB)
    details: Mapped[dict] = mapped_column(JSONB)


# ------------------------------------------------------------------- review evidence
# Explicitly published projection of the two accepted EVALUATION_ONLY capabilities (forecast stress
# tests and constrained decision alternatives). Human-review evidence only: never operational signals,
# recommendations, routing, capacity checks or causal claims. Request-time code reads only these tables.
class ReviewEvidenceSnapshot(Base):
    __tablename__ = "review_evidence_snapshot"
    __table_args__ = (
        UniqueConstraint("publication_id", name="uq_review_evidence_snapshot_publication_id"),
        UniqueConstraint("publication_identity_sha256", name="uq_review_evidence_snapshot_identity"),
        Index(
            "ux_review_evidence_snapshot_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    publication_id: Mapped[str] = mapped_column(String(128))
    schema_version: Mapped[str] = mapped_column(String(64))
    contract_version: Mapped[str] = mapped_column(String(32))
    publication_identity_sha256: Mapped[str] = mapped_column(String(64))
    bundle_sha256: Mapped[str] = mapped_column(String(64))
    assurance_identity_sha256: Mapped[str] = mapped_column(String(64))
    operational_publication_identity_sha256: Mapped[str] = mapped_column(String(64))
    source_code_commit: Mapped[str] = mapped_column(String(40))
    current_origin: Mapped[dt.date] = mapped_column(Date)
    freshness_state: Mapped[str] = mapped_column(String(16))
    publication_status: Mapped[str] = mapped_column(String(16))
    generated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), index=True)
    scenario_count: Mapped[int] = mapped_column(Integer)
    scenario_entity_count: Mapped[int] = mapped_column(Integer)
    scenario_cell_count: Mapped[int] = mapped_column(Integer)
    alternative_set_count: Mapped[int] = mapped_column(Integer)
    alternative_count: Mapped[int] = mapped_column(Integer)
    source_provenance: Mapped[dict] = mapped_column(JSONB)
    limitations: Mapped[list] = mapped_column(JSONB)
    alternatives_summary: Mapped[dict] = mapped_column(JSONB)


class ReviewScenario(Base):
    __tablename__ = "review_scenario"
    __table_args__ = (UniqueConstraint("snapshot_id", "scenario_id", name="uq_review_scenario_snapshot_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("review_evidence_snapshot.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(128))
    scenario_type: Mapped[str] = mapped_column(String(32))
    classification: Mapped[str] = mapped_column(String(48))
    lever_type: Mapped[str] = mapped_column(String(64))
    multiplier: Mapped[float | None] = mapped_column(Double)
    scope_type: Mapped[str] = mapped_column(String(64))
    horizon_start: Mapped[int] = mapped_column(SmallInteger)
    horizon_end: Mapped[int] = mapped_column(SmallInteger)
    target: Mapped[str] = mapped_column(String(32))
    uncertainty_method: Mapped[str] = mapped_column(String(64))
    uncertainty_label: Mapped[str] = mapped_column(String(64))
    coverage_guarantee: Mapped[bool] = mapped_column(Boolean)
    causal_effect_claimed: Mapped[bool] = mapped_column(Boolean)
    serving_claim: Mapped[bool] = mapped_column(Boolean)
    baseline_reproduction: Mapped[str | None] = mapped_column(String(16))
    details: Mapped[dict] = mapped_column(JSONB)


class ReviewScenarioEntity(Base):
    __tablename__ = "review_scenario_entity"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "scenario_id",
            "series_id",
            "target",
            "origin",
            name="uq_review_scenario_entity",
        ),
        Index("ix_review_scenario_entity_signal", "snapshot_id", "signal_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("review_evidence_snapshot.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(128))
    series_id: Mapped[str] = mapped_column(String(64))
    origin: Mapped[dt.date] = mapped_column(Date)
    target: Mapped[str] = mapped_column(String(32))
    org_code: Mapped[str] = mapped_column(String(8))
    region_code: Mapped[str] = mapped_column(String(4))
    profile_code: Mapped[str] = mapped_column(String(8))
    signal_id: Mapped[str] = mapped_column(String(128))
    baseline_severity: Mapped[str] = mapped_column(String(16))
    scenario_severity: Mapped[str] = mapped_column(String(16))
    baseline_inbox_rank: Mapped[int | None] = mapped_column(Integer)
    scenario_inbox_rank: Mapped[int | None] = mapped_column(Integer)
    baseline_central: Mapped[float] = mapped_column(Double)
    scenario_central: Mapped[float] = mapped_column(Double)
    threshold_value: Mapped[float | None] = mapped_column(Double)
    absolute_delta: Mapped[float] = mapped_column(Double)
    relative_delta: Mapped[float | None] = mapped_column(Double)
    severity_changed: Mapped[bool] = mapped_column(Boolean)
    entered_primary_inbox: Mapped[bool] = mapped_column(Boolean)
    left_primary_inbox: Mapped[bool] = mapped_column(Boolean)
    first_crossing_date: Mapped[dt.date | None] = mapped_column(Date)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    materiality_status: Mapped[str | None] = mapped_column(String(64))
    scenario_headline: Mapped[str | None] = mapped_column(Text)
    scenario_reason: Mapped[str | None] = mapped_column(Text)
    scenario_range_available: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(JSONB)


class ReviewScenarioCell(Base):
    __tablename__ = "review_scenario_cell"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "scenario_id",
            "series_id",
            "target",
            "origin",
            "target_date",
            name="uq_review_scenario_cell",
        ),
        Index("ix_review_scenario_cell_series", "snapshot_id", "series_id", "target", "origin", "scenario_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("review_evidence_snapshot.id", ondelete="CASCADE"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(128))
    series_id: Mapped[str] = mapped_column(String(64))
    origin: Mapped[dt.date] = mapped_column(Date)
    target: Mapped[str] = mapped_column(String(32))
    target_date: Mapped[dt.date] = mapped_column(Date)
    horizon: Mapped[int] = mapped_column(SmallInteger)
    baseline_central: Mapped[float] = mapped_column(Double)
    baseline_lower: Mapped[float | None] = mapped_column(Double)
    baseline_upper: Mapped[float | None] = mapped_column(Double)
    baseline_severity: Mapped[str] = mapped_column(String(16))
    scenario_central: Mapped[float] = mapped_column(Double)
    scenario_lower: Mapped[float | None] = mapped_column(Double)
    scenario_upper: Mapped[float | None] = mapped_column(Double)
    scenario_severity: Mapped[str] = mapped_column(String(16))
    threshold_value: Mapped[float | None] = mapped_column(Double)
    threshold_status: Mapped[str | None] = mapped_column(String(32))
    scenario_uncertainty_status: Mapped[str] = mapped_column(String(48))
    severity_changed: Mapped[bool] = mapped_column(Boolean)
    source_reason_code: Mapped[str | None] = mapped_column(String(96))


class ReviewAlternativeSet(Base):
    __tablename__ = "review_alternative_set"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "set_id", name="uq_review_alternative_set_snapshot_id"),
        Index("ix_review_alternative_set_signal", "snapshot_id", "signal_id"),
        Index("ix_review_alternative_set_scope", "snapshot_id", "origin", "region_code", "org_code", "profile_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("review_evidence_snapshot.id", ondelete="CASCADE"), index=True)
    set_id: Mapped[str] = mapped_column(String(128))
    canonical_unit_id: Mapped[str] = mapped_column(String(128))
    origin: Mapped[dt.date] = mapped_column(Date)
    target: Mapped[str] = mapped_column(String(32))
    signal_id: Mapped[str] = mapped_column(String(128))
    org_code: Mapped[str] = mapped_column(String(8))
    profile_code: Mapped[str] = mapped_column(String(8))
    region_code: Mapped[str] = mapped_column(String(4))
    series_id: Mapped[str] = mapped_column(String(64))
    donor_severity: Mapped[str] = mapped_column(String(16))
    priority_support_class: Mapped[str] = mapped_column(String(64))
    materiality_status: Mapped[str | None] = mapped_column(String(64))
    budget: Mapped[float] = mapped_column(Double)
    abstained: Mapped[bool] = mapped_column(Boolean)
    abstention_codes: Mapped[list] = mapped_column(JSONB)
    receiver_candidates_considered: Mapped[int] = mapped_column(Integer)
    receiver_candidates_eligible: Mapped[int] = mapped_column(Integer)
    donor_minimum_transfer_fraction: Mapped[float | None] = mapped_column(Double)
    shortlist_bound: Mapped[int] = mapped_column(Integer)
    alternative_count: Mapped[int] = mapped_column(Integer)
    verification_failure_count: Mapped[int] = mapped_column(Integer)
    scientific_output_sha256: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB)


class ReviewAlternative(Base):
    __tablename__ = "review_alternative"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "set_id", "alternative_id", name="uq_review_alternative_snapshot_id"),
        Index("ix_review_alternative_set", "snapshot_id", "set_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("review_evidence_snapshot.id", ondelete="CASCADE"), index=True)
    set_id: Mapped[str] = mapped_column(String(128))
    alternative_id: Mapped[str] = mapped_column(String(128))
    position: Mapped[int] = mapped_column(SmallInteger)
    donor_org_code: Mapped[str] = mapped_column(String(8))
    receiver_org_code: Mapped[str] = mapped_column(String(8))
    profile_code: Mapped[str] = mapped_column(String(8))
    region_code: Mapped[str] = mapped_column(String(4))
    transfer_fraction: Mapped[float] = mapped_column(Double)
    transferred_total: Mapped[float] = mapped_column(Double)
    donor_severity_before: Mapped[str] = mapped_column(String(16))
    donor_severity_after: Mapped[str] = mapped_column(String(16))
    receiver_severity_before: Mapped[str] = mapped_column(String(16))
    receiver_severity_after: Mapped[str] = mapped_column(String(16))
    verification_state: Mapped[str] = mapped_column(String(32))
    forecast_support_tier: Mapped[str] = mapped_column(String(32))
    receiver_range_evidence: Mapped[str] = mapped_column(String(16))
    sensitivity_range_result: Mapped[str] = mapped_column(String(48))
    feasibility_status: Mapped[str] = mapped_column(String(48))
    receiver_no_worse_constraint_satisfied: Mapped[bool] = mapped_column(Boolean)
    conservation_satisfied: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict] = mapped_column(JSONB)


# ------------------------------------------------------------------ serving marts
# Filled by ml/pipelines/build_marts.py (`make marts`, also at the end of `make predict`): one
# transaction truncates and rebuilds all mart_* tables. No FKs to the data layer on purpose —
# `make ingest` truncates the dictionaries and facts. Formulas: docs/api.md.
class _StatusMetrics:
    """Columns shared by the hospital × profile and region × profile marts."""

    as_of_date: Mapped[dt.date] = mapped_column(Date)
    queue_now: Mapped[int] = mapped_column(Integer)
    registrations_28d: Mapped[int] = mapped_column(Integer)
    hospitalizations_28d: Mapped[int] = mapped_column(Integer)
    refusals_28d: Mapped[int] = mapped_column(Integer)
    refusal_rate_28d: Mapped[float | None] = mapped_column(Double)
    n_waits_28d: Mapped[int] = mapped_column(Integer)
    median_wait_28d: Mapped[float | None] = mapped_column(Double)
    daily_throughput_28d: Mapped[float] = mapped_column(Double)
    backlog_days: Mapped[float | None] = mapped_column(Double)
    forecast_registrations_14d: Mapped[float | None] = mapped_column(Double)
    forecast_hospitalizations_14d: Mapped[float | None] = mapped_column(Double)
    n_test_referrals: Mapped[int] = mapped_column(Integer)
    high_risk_share: Mapped[float | None] = mapped_column(Double)
    queue_trend_raw_4w: Mapped[float | None] = mapped_column(Double)  # % of mean weekly queue per week
    queue_trend_4w: Mapped[float | None] = mapped_column(Double)  # excess: raw − national median trend
    has_sufficient_data: Mapped[bool] = mapped_column(Boolean)
    backlog_score: Mapped[float | None] = mapped_column(Double)
    refusal_score: Mapped[float | None] = mapped_column(Double)
    trend_score: Mapped[float | None] = mapped_column(Double)
    load_index: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(24))  # high | elevated | normal | insufficient_data


class MartHospitalProfileStatus(_StatusMetrics, Base):
    __tablename__ = "mart_hospital_profile_status"
    __table_args__ = (Index("ix_mart_hps_region_profile", "region_code", "profile_code"),)

    org_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    profile_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    region_code: Mapped[str] = mapped_column(String(4))
    region_name: Mapped[str] = mapped_column(Text)
    org_name: Mapped[str] = mapped_column(Text)
    profile_name: Mapped[str] = mapped_column(Text)
    forecast_method: Mapped[str | None] = mapped_column(String(32))
    region_rank: Mapped[int | None] = mapped_column(Integer)  # rank of load_index within the region (1 = highest)
    region_n_ranked: Mapped[int] = mapped_column(Integer)  # rows with a load_index in the region
    in_region_top: Mapped[bool] = mapped_column(Boolean)  # region_rank <= ceil(region_top_fraction * region_n_ranked)


class MartRegionProfileStatus(_StatusMetrics, Base):
    __tablename__ = "mart_region_profile_status"

    region_code: Mapped[str] = mapped_column(String(4), primary_key=True)
    profile_code: Mapped[str] = mapped_column(String(8), primary_key=True)
    region_name: Mapped[str] = mapped_column(Text)
    profile_name: Mapped[str] = mapped_column(Text)
    n_hospitals: Mapped[int] = mapped_column(Integer)
    n_hospitals_high_load: Mapped[int] = mapped_column(Integer)
    load_index_max_hospital: Mapped[float | None] = mapped_column(Double)


class MartAreaStatus(Base):
    """Totals over all profiles: one national row (area_code 'KZ') and one row per region."""

    __tablename__ = "mart_area_status"

    area_code: Mapped[str] = mapped_column(String(4), primary_key=True)
    area_level: Mapped[str] = mapped_column(String(16))  # national | region
    area_name: Mapped[str] = mapped_column(Text)
    as_of_date: Mapped[dt.date] = mapped_column(Date)
    queue_now: Mapped[int] = mapped_column(Integer)
    registrations_28d: Mapped[int] = mapped_column(Integer)
    hospitalizations_28d: Mapped[int] = mapped_column(Integer)
    refusals_28d: Mapped[int] = mapped_column(Integer)
    refusal_rate_28d: Mapped[float | None] = mapped_column(Double)
    n_waits_28d: Mapped[int] = mapped_column(Integer)
    median_wait_28d: Mapped[float | None] = mapped_column(Double)
    forecast_registrations_14d: Mapped[float | None] = mapped_column(Double)
    forecast_hospitalizations_14d: Mapped[float | None] = mapped_column(Double)
    high_risk_share: Mapped[float | None] = mapped_column(Double)
    n_hospitals: Mapped[int] = mapped_column(Integer)
    n_hospital_profiles: Mapped[int] = mapped_column(Integer)
    n_hospital_profiles_ranked: Mapped[int] = mapped_column(Integer)
    load_index_max: Mapped[float | None] = mapped_column(Double)
    n_hospitals_high_load: Mapped[int] = mapped_column(Integer)
    n_hospital_profiles_high_load: Mapped[int] = mapped_column(Integer)


class MartBuildInfo(Base):
    """One row (id = 1): when the marts were built and with which ml/configs/serving.yaml."""

    __tablename__ = "mart_build_info"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date)
    built_at: Mapped[dt.datetime] = mapped_column(DateTime)
    config: Mapped[dict] = mapped_column(JSONB)
    row_counts: Mapped[dict] = mapped_column(JSONB)


# ------------------------------------------------------------- human in the loop
class DecisionLog(Base):
    """Decisions of a person on a hospital × profile (and optionally a recommendation). Never
    truncated by the pipelines."""

    __tablename__ = "decision_log"
    __table_args__ = (
        CheckConstraint("action IN ('confirm', 'reject', 'defer')", name="ck_decision_log_action"),
        Index("ix_decision_log_org_profile", "org_code", "profile_code"),
        Index(
            "ux_decision_log_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    region_code: Mapped[str] = mapped_column(String(4))
    org_code: Mapped[str] = mapped_column(String(8))
    profile_code: Mapped[str] = mapped_column(String(8))
    recommendation_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(Text)  # free text typed by the person
    alternative_org_code: Mapped[str | None] = mapped_column(String(8))  # the recommended hospital, if any
    idempotency_key: Mapped[str | None] = mapped_column(String(128))  # client-supplied; a retry returns the row
    api_key_label: Mapped[str | None] = mapped_column(Text)  # label of the API key that submitted it


class SpecialistDecision(Base):
    """A specialist's answer in the control centre: to a published alert or to a synthetic admission request.
    Keyed by the publication origin and the subject id, so a reload of the demo can restore it. Never truncated
    by the pipelines."""

    __tablename__ = "specialist_decision"
    __table_args__ = (
        CheckConstraint("subject_kind IN ('alert', 'patient')", name="ck_specialist_decision_subject_kind"),
        CheckConstraint(
            "action IN ('accept', 'decline', 'clarify', 'confirm', 'postpone')",
            name="ck_specialist_decision_action",
        ),
        Index("ix_specialist_decision_subject", "subject_kind", "subject_id"),
        Index(
            "ux_specialist_decision_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    origin: Mapped[dt.date] = mapped_column(Date, index=True)  # publication origin the decision belongs to
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)  # simulation run; a restart starts a new one
    sim_day: Mapped[int] = mapped_column(Integer)  # day of the demo simulation (0 = origin)
    subject_kind: Mapped[str] = mapped_column(String(16))  # alert | patient
    subject_id: Mapped[str] = mapped_column(String(64))  # signal id or synthetic referral id
    region_code: Mapped[str | None] = mapped_column(String(4))
    org_code: Mapped[str | None] = mapped_column(String(8))
    profile_code: Mapped[str | None] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str | None] = mapped_column(Text)
    api_key_label: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))


# ------------------------------------------------------------------ access control
class ApiKey(Base):
    """API keys (only the SHA-256 of the key is stored). role: viewer < specialist < admin."""

    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("role IN ('viewer', 'specialist', 'admin')", name="ck_api_keys_role"),
        Index("ux_api_keys_key_hash", "key_hash", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    key_prefix: Mapped[str] = mapped_column(String(16))  # first characters, to recognise a key in lists and logs
    role: Mapped[str] = mapped_column(String(16))
    label: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class AccessLog(Base):
    """One row per /api request, written by app.core.access_log after the response."""

    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    key_label: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str | None] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[int] = mapped_column(SmallInteger)
    latency_ms: Mapped[float] = mapped_column(Double)
    client_ip: Mapped[str | None] = mapped_column(String(64))  # TCP peer (the nginx container behind the proxy)
    forwarded_for: Mapped[str | None] = mapped_column(Text)  # X-Forwarded-For as received — not verified
