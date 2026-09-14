"""initial data layer

Revision ID: 0001
Revises:
Create Date: 2026-09-14 16:39:02.433935

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('agg_daily_admission_refusals',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('org_code', sa.String(length=8), nullable=False),
    sa.Column('region_code', sa.String(length=4), nullable=True),
    sa.Column('refusals', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('date', 'org_code')
    )
    op.create_index(op.f('ix_agg_daily_admission_refusals_org_code'), 'agg_daily_admission_refusals', ['org_code'], unique=False)
    op.create_index(op.f('ix_agg_daily_admission_refusals_region_code'), 'agg_daily_admission_refusals', ['region_code'], unique=False)
    op.create_table('agg_daily_hospital_profile',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('org_code', sa.String(length=8), nullable=False),
    sa.Column('profile_code', sa.String(length=8), nullable=False),
    sa.Column('region_code', sa.String(length=4), nullable=True),
    sa.Column('registrations', sa.Integer(), nullable=False),
    sa.Column('hospitalizations', sa.Integer(), nullable=False),
    sa.Column('refusals', sa.Integer(), nullable=False),
    sa.Column('queue_length', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('date', 'org_code', 'profile_code')
    )
    op.create_index(op.f('ix_agg_daily_hospital_profile_org_code'), 'agg_daily_hospital_profile', ['org_code'], unique=False)
    op.create_index(op.f('ix_agg_daily_hospital_profile_profile_code'), 'agg_daily_hospital_profile', ['profile_code'], unique=False)
    op.create_index(op.f('ix_agg_daily_hospital_profile_region_code'), 'agg_daily_hospital_profile', ['region_code'], unique=False)
    op.create_table('agg_daily_region_profile',
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('region_code', sa.String(length=4), nullable=False),
    sa.Column('profile_code', sa.String(length=8), nullable=False),
    sa.Column('registrations', sa.Integer(), nullable=False),
    sa.Column('hospitalizations', sa.Integer(), nullable=False),
    sa.Column('refusals', sa.Integer(), nullable=False),
    sa.Column('queue_length', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('date', 'region_code', 'profile_code')
    )
    op.create_index(op.f('ix_agg_daily_region_profile_profile_code'), 'agg_daily_region_profile', ['profile_code'], unique=False)
    op.create_index(op.f('ix_agg_daily_region_profile_region_code'), 'agg_daily_region_profile', ['region_code'], unique=False)
    op.create_table('dim_profile',
    sa.Column('profile_code', sa.String(length=8), nullable=False),
    sa.Column('profile_name', sa.Text(), nullable=True),
    sa.Column('name_share', sa.Double(), nullable=True),
    sa.Column('n_referrals', sa.Integer(), nullable=False),
    sa.Column('is_day_hospital', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('profile_code')
    )
    op.create_table('dim_region',
    sa.Column('region_code', sa.String(length=4), nullable=False),
    sa.Column('region_name', sa.Text(), nullable=False),
    sa.Column('vote_region_name', sa.Text(), nullable=True),
    sa.Column('vote_share', sa.Double(), nullable=True),
    sa.Column('vote_referrals', sa.Integer(), nullable=True),
    sa.Column('runner_up_name', sa.Text(), nullable=True),
    sa.Column('runner_up_share', sa.Double(), nullable=True),
    sa.Column('is_ambiguous', sa.Boolean(), nullable=False),
    sa.Column('manual_override', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('region_code')
    )
    op.create_table('ersb_snapshot',
    sa.Column('ersb_id', sa.Integer(), nullable=False),
    sa.Column('org_name', sa.Text(), nullable=False),
    sa.Column('org_key', sa.Text(), nullable=False),
    sa.Column('discharged_total', sa.Integer(), nullable=False),
    sa.Column('discharged_children', sa.Integer(), nullable=False),
    sa.Column('treated_budget', sa.Integer(), nullable=False),
    sa.Column('treated_paid', sa.Integer(), nullable=False),
    sa.Column('discharged_within_day', sa.Integer(), nullable=False),
    sa.Column('deaths_total', sa.Integer(), nullable=False),
    sa.Column('bed_days', sa.Integer(), nullable=False),
    sa.Column('amount_to_pay', sa.Numeric(precision=20, scale=2), nullable=True),
    sa.Column('avg_length_of_stay', sa.Double(), nullable=True),
    sa.Column('org_code', sa.String(length=8), nullable=True),
    sa.Column('n_matched_org_codes', sa.Integer(), nullable=False),
    sa.Column('sdu_load_date', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('ersb_id')
    )
    op.create_index(op.f('ix_ersb_snapshot_org_code'), 'ersb_snapshot', ['org_code'], unique=False)
    op.create_index(op.f('ix_ersb_snapshot_org_key'), 'ersb_snapshot', ['org_key'], unique=False)
    op.create_table('dim_organization',
    sa.Column('org_code', sa.String(length=8), nullable=False),
    sa.Column('org_name', sa.Text(), nullable=False),
    sa.Column('org_key', sa.Text(), nullable=False),
    sa.Column('region_code', sa.String(length=4), nullable=True),
    sa.Column('region_method', sa.String(length=32), nullable=True),
    sa.Column('n_referrals', sa.Integer(), nullable=False),
    sa.Column('n_origin_regions', sa.Integer(), nullable=False),
    sa.Column('ersb_id', sa.Integer(), nullable=True),
    sa.Column('match_score', sa.Double(), nullable=True),
    sa.Column('match_method', sa.String(length=16), nullable=True),
    sa.ForeignKeyConstraint(['ersb_id'], ['ersb_snapshot.ersb_id'], ),
    sa.ForeignKeyConstraint(['region_code'], ['dim_region.region_code'], ),
    sa.PrimaryKeyConstraint('org_code')
    )
    op.create_index(op.f('ix_dim_organization_org_key'), 'dim_organization', ['org_key'], unique=False)
    op.create_index(op.f('ix_dim_organization_region_code'), 'dim_organization', ['region_code'], unique=False)
    op.create_table('fact_admission_refusal',
    sa.Column('refusal_id', sa.BigInteger(), nullable=False),
    sa.Column('source_part', sa.SmallInteger(), nullable=False),
    sa.Column('region_in', sa.Text(), nullable=True),
    sa.Column('region_code', sa.String(length=4), nullable=True),
    sa.Column('org_in', sa.Text(), nullable=True),
    sa.Column('org_code', sa.String(length=8), nullable=True),
    sa.Column('org_match_method', sa.String(length=16), nullable=True),
    sa.Column('resident', sa.String(length=16), nullable=True),
    sa.Column('insured', sa.String(length=32), nullable=True),
    sa.Column('benefit_cat', sa.Text(), nullable=True),
    sa.Column('refuse_dt', sa.DateTime(), nullable=False),
    sa.Column('refuse_date', sa.Date(), nullable=False),
    sa.Column('attach_region', sa.Text(), nullable=True),
    sa.Column('attach_region_code', sa.String(length=4), nullable=True),
    sa.Column('attach_org', sa.Text(), nullable=True),
    sa.Column('icd10_code', sa.String(length=16), nullable=True),
    sa.Column('icd_name', sa.Text(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('finance_src', sa.Text(), nullable=True),
    sa.Column('sdu_load_date', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['org_code'], ['dim_organization.org_code'], ),
    sa.ForeignKeyConstraint(['region_code'], ['dim_region.region_code'], ),
    sa.PrimaryKeyConstraint('refusal_id')
    )
    op.create_index(op.f('ix_fact_admission_refusal_org_code'), 'fact_admission_refusal', ['org_code'], unique=False)
    op.create_index(op.f('ix_fact_admission_refusal_refuse_date'), 'fact_admission_refusal', ['refuse_date'], unique=False)
    op.create_index(op.f('ix_fact_admission_refusal_region_code'), 'fact_admission_refusal', ['region_code'], unique=False)
    op.create_table('fact_referral',
    sa.Column('referral_id', sa.BigInteger(), nullable=False),
    sa.Column('hospitalization_code', sa.String(length=32), nullable=False),
    sa.Column('region_code', sa.String(length=4), nullable=False),
    sa.Column('org_code', sa.String(length=8), nullable=False),
    sa.Column('profile_code', sa.String(length=8), nullable=False),
    sa.Column('seq_no', sa.String(length=16), nullable=True),
    sa.Column('is_dup_code', sa.Boolean(), nullable=False),
    sa.Column('hospital_region_code', sa.String(length=4), nullable=True),
    sa.Column('referring_mo', sa.Text(), nullable=True),
    sa.Column('hospital_mo', sa.Text(), nullable=True),
    sa.Column('icd10_code', sa.String(length=16), nullable=True),
    sa.Column('diagnosis_name', sa.Text(), nullable=True),
    sa.Column('bed_profile', sa.Text(), nullable=True),
    sa.Column('registration_dt', sa.DateTime(), nullable=False),
    sa.Column('planned_dt_raw', sa.DateTime(), nullable=True),
    sa.Column('planned_dt', sa.DateTime(), nullable=True),
    sa.Column('polyclinic_dt', sa.DateTime(), nullable=True),
    sa.Column('hospitalization_dt', sa.DateTime(), nullable=True),
    sa.Column('refusal_dt', sa.DateTime(), nullable=True),
    sa.Column('territorial_type', sa.String(length=16), nullable=True),
    sa.Column('referral_purpose', sa.Text(), nullable=True),
    sa.Column('finance_source', sa.Text(), nullable=True),
    sa.Column('sdu_load_date', sa.DateTime(), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('outcome_conflict', sa.Boolean(), nullable=False),
    sa.Column('registration_date', sa.Date(), nullable=False),
    sa.Column('registration_weekday', sa.SmallInteger(), nullable=False),
    sa.Column('planned_week', sa.Date(), nullable=True),
    sa.Column('hospitalization_date', sa.Date(), nullable=True),
    sa.Column('refusal_date', sa.Date(), nullable=True),
    sa.Column('resolution_date', sa.Date(), nullable=True),
    sa.Column('wait_days', sa.Integer(), nullable=True),
    sa.Column('wait_to_refusal_days', sa.Integer(), nullable=True),
    sa.Column('same_day_registration', sa.Boolean(), nullable=False),
    sa.Column('retro_registration', sa.Boolean(), nullable=False),
    sa.Column('planned_dt_out_of_range', sa.Boolean(), nullable=False),
    sa.Column('planned_lag_days', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['org_code'], ['dim_organization.org_code'], ),
    sa.ForeignKeyConstraint(['profile_code'], ['dim_profile.profile_code'], ),
    sa.ForeignKeyConstraint(['region_code'], ['dim_region.region_code'], ),
    sa.PrimaryKeyConstraint('referral_id')
    )
    op.create_index(op.f('ix_fact_referral_hospital_region_code'), 'fact_referral', ['hospital_region_code'], unique=False)
    op.create_index(op.f('ix_fact_referral_hospitalization_code'), 'fact_referral', ['hospitalization_code'], unique=False)
    op.create_index(op.f('ix_fact_referral_hospitalization_date'), 'fact_referral', ['hospitalization_date'], unique=False)
    op.create_index(op.f('ix_fact_referral_org_code'), 'fact_referral', ['org_code'], unique=False)
    op.create_index(op.f('ix_fact_referral_outcome'), 'fact_referral', ['outcome'], unique=False)
    op.create_index(op.f('ix_fact_referral_profile_code'), 'fact_referral', ['profile_code'], unique=False)
    op.create_index(op.f('ix_fact_referral_region_code'), 'fact_referral', ['region_code'], unique=False)
    op.create_index(op.f('ix_fact_referral_registration_date'), 'fact_referral', ['registration_date'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_fact_referral_registration_date'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_region_code'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_profile_code'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_outcome'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_org_code'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_hospitalization_date'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_hospitalization_code'), table_name='fact_referral')
    op.drop_index(op.f('ix_fact_referral_hospital_region_code'), table_name='fact_referral')
    op.drop_table('fact_referral')
    op.drop_index(op.f('ix_fact_admission_refusal_region_code'), table_name='fact_admission_refusal')
    op.drop_index(op.f('ix_fact_admission_refusal_refuse_date'), table_name='fact_admission_refusal')
    op.drop_index(op.f('ix_fact_admission_refusal_org_code'), table_name='fact_admission_refusal')
    op.drop_table('fact_admission_refusal')
    op.drop_index(op.f('ix_dim_organization_region_code'), table_name='dim_organization')
    op.drop_index(op.f('ix_dim_organization_org_key'), table_name='dim_organization')
    op.drop_table('dim_organization')
    op.drop_index(op.f('ix_ersb_snapshot_org_key'), table_name='ersb_snapshot')
    op.drop_index(op.f('ix_ersb_snapshot_org_code'), table_name='ersb_snapshot')
    op.drop_table('ersb_snapshot')
    op.drop_table('dim_region')
    op.drop_table('dim_profile')
    op.drop_index(op.f('ix_agg_daily_region_profile_region_code'), table_name='agg_daily_region_profile')
    op.drop_index(op.f('ix_agg_daily_region_profile_profile_code'), table_name='agg_daily_region_profile')
    op.drop_table('agg_daily_region_profile')
    op.drop_index(op.f('ix_agg_daily_hospital_profile_region_code'), table_name='agg_daily_hospital_profile')
    op.drop_index(op.f('ix_agg_daily_hospital_profile_profile_code'), table_name='agg_daily_hospital_profile')
    op.drop_index(op.f('ix_agg_daily_hospital_profile_org_code'), table_name='agg_daily_hospital_profile')
    op.drop_table('agg_daily_hospital_profile')
    op.drop_index(op.f('ix_agg_daily_admission_refusals_region_code'), table_name='agg_daily_admission_refusals')
    op.drop_index(op.f('ix_agg_daily_admission_refusals_org_code'), table_name='agg_daily_admission_refusals')
    op.drop_table('agg_daily_admission_refusals')
