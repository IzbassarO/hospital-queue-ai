"""Data-layer tables. Filled by ml/pipelines/ingest.py; column semantics in docs/data.md.

Column names here must match the Parquet files written by hqai_ml.ingest
(the loader COPYs by column name).
"""
import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    Double,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    DateTime,
)
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
