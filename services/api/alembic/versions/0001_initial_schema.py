"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-09-25 15:04:55.834702
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('call_summaries',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('call_id', sa.Text(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('language', sa.Text(), nullable=True),
    sa.Column('caller_number', sa.Text(), nullable=True),
    sa.Column('intent', sa.Text(), nullable=False),
    sa.Column('outcome', sa.Text(), nullable=False),
    sa.Column('transferred_to', sa.Text(), nullable=True),
    sa.Column('appointment_id', sa.Text(), nullable=True),
    sa.Column('tool_outcomes', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('summary_text', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('call_id')
    )
    op.create_table('departments',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('code', sa.Text(), nullable=True),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('localized_names', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('has_consultant', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('doctors',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('localized_names', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('name_variants', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('gender', sa.Text(), nullable=True),
    sa.Column('qualification', sa.Text(), nullable=True),
    sa.Column('years_of_experience', sa.Integer(), nullable=True),
    sa.Column('languages_spoken', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('fee_amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('fee_currency', sa.Text(), nullable=True),
    sa.Column('fee_confirmed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('attendance_type', sa.Text(), server_default='REGULAR', nullable=False),
    sa.Column('booking_policy', sa.Text(), server_default='BOOKABLE', nullable=False),
    sa.Column('data_confirmed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("attendance_type IN ('REGULAR', 'VISITING', 'ON_CALL')", name='attendance'),
    sa.CheckConstraint("booking_policy IN ('BOOKABLE', 'DESK_ONLY', 'NO_OPD')", name='policy'),
    sa.CheckConstraint("gender IN ('FEMALE', 'MALE')", name='gender'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('idempotency_keys',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('request_hash', sa.Text(), nullable=False),
    sa.Column('status', sa.Integer(), nullable=False),
    sa.Column('body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_index(op.f('ix_idempotency_keys_created_at'), 'idempotency_keys', ['created_at'], unique=False)
    op.create_table('lexicon_entries',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('concept_type', sa.Text(), nullable=False),
    sa.Column('concept_id', sa.Text(), nullable=False),
    sa.Column('term', sa.Text(), nullable=False),
    sa.Column('term_normalized', sa.Text(), nullable=False),
    sa.Column('language', sa.Text(), nullable=False),
    sa.Column('approved', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('source', sa.Text(), server_default='HOSPITAL', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("concept_type IN ('DEPARTMENT', 'DOCTOR', 'SYMPTOM_ROUTE', 'RED_FLAG', 'DAY_PART', 'SERVICE_TRANSFER')", name='concept_type'),
    sa.CheckConstraint("source IN ('HOSPITAL', 'TRANSCRIPT_MINED', 'AUTO_TRANSLITERATION')", name='source'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('concept_type', 'concept_id', 'term', 'language', name='lexicon_term')
    )
    op.create_index('ix_lexicon_approved_type', 'lexicon_entries', ['approved', 'concept_type'], unique=False)
    op.create_table('appointments',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('confirmation_code', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('patient_name', sa.Text(), nullable=False),
    sa.Column('patient_name_normalized', sa.Text(), nullable=False),
    sa.Column('phone', sa.Text(), nullable=False),
    sa.Column('relation_to_caller', sa.Text(), nullable=True),
    sa.Column('caller_number', sa.Text(), nullable=True),
    sa.Column('doctor_id', sa.Text(), nullable=False),
    sa.Column('department_id', sa.Text(), nullable=True),
    sa.Column('session_id', sa.Text(), nullable=False),
    sa.Column('slot_id', sa.Text(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('timing_confirmed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('confirmed_start', sa.Time(), nullable=True),
    sa.Column('reason_verbatim', sa.Text(), nullable=True),
    sa.Column('language', sa.Text(), nullable=True),
    sa.Column('created_via', sa.Text(), nullable=False),
    sa.Column('call_id', sa.Text(), nullable=True),
    sa.Column('follow_up', sa.Text(), server_default='NONE', nullable=False),
    sa.Column('impacted_by_exception_id', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("created_via IN ('AGENT', 'DESK', 'WEB')", name='created_via'),
    sa.CheckConstraint("follow_up IN ('NONE', 'DESK_WILL_CONFIRM_TIMING')", name='follow_up'),
    sa.CheckConstraint("status IN ('BOOKED', 'CONFIRMED_BY_DESK', 'RESCHEDULED', 'NEEDS_RESCHEDULE', 'ARRIVED', 'COMPLETED', 'NO_SHOW', 'CANCELLED_BY_PATIENT', 'CANCELLED_BY_HOSPITAL')", name='status'),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_appointments_caller_number', 'appointments', ['caller_number'], unique=False)
    op.create_index('ix_appointments_doctor_date', 'appointments', ['doctor_id', 'date'], unique=False)
    op.create_index('ix_appointments_phone', 'appointments', ['phone'], unique=False)
    op.create_index('ix_appointments_session', 'appointments', ['session_id'], unique=False)
    op.create_index('uq_appointments_live_slot', 'appointments', ['slot_id'], unique=True, postgresql_where=sa.text("status IN ('BOOKED', 'CONFIRMED_BY_DESK', 'RESCHEDULED', 'ARRIVED')"))
    op.create_table('board_entries',
    sa.Column('session_id', sa.Text(), nullable=False),
    sa.Column('doctor_id', sa.Text(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('presence', sa.Text(), nullable=True),
    sa.Column('expected_start', sa.Time(), nullable=True),
    sa.Column('delay_minutes', sa.Integer(), nullable=True),
    sa.Column('session_ended', sa.Boolean(), nullable=True),
    sa.Column('capacity_state', sa.Text(), nullable=True),
    sa.Column('tokens_issued', sa.Integer(), nullable=True),
    sa.Column('last_arrival_time', sa.Time(), nullable=True),
    sa.Column('timing_confirmed', sa.Boolean(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_by', sa.Text(), nullable=False),
    sa.CheckConstraint("capacity_state IN ('OPEN', 'FULL')", name='capacity_state'),
    sa.CheckConstraint("presence IN ('NOT_ARRIVED', 'ARRIVING', 'PRESENT', 'LEFT')", name='presence'),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('session_id')
    )
    op.create_index('ix_board_doctor_date', 'board_entries', ['doctor_id', 'date'], unique=False)
    op.create_table('doctor_departments',
    sa.Column('doctor_id', sa.Text(), nullable=False),
    sa.Column('department_id', sa.Text(), nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('doctor_id', 'department_id')
    )
    op.create_table('schedule_exceptions',
    sa.Column('seq', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('doctor_id', sa.Text(), nullable=False),
    sa.Column('date_from', sa.Date(), nullable=False),
    sa.Column('date_to', sa.Date(), nullable=False),
    sa.Column('scope', sa.Text(), nullable=False),
    sa.Column('template_session_id', sa.Text(), nullable=True),
    sa.Column('effect', sa.Text(), nullable=False),
    sa.Column('new_start', sa.Time(), nullable=True),
    sa.Column('new_end', sa.Time(), nullable=True),
    sa.Column('new_capacity', sa.Integer(), nullable=True),
    sa.Column('reason_category', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Text(), nullable=False),
    sa.Column('impact_appointments', sa.Integer(), server_default='0', nullable=False),
    sa.Column('impact_notifications', sa.Integer(), server_default='0', nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deleted_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("effect IN ('UNAVAILABLE', 'TIME_CHANGE', 'CAPACITY_CHANGE', 'EXTRA_SESSION', 'TIMING_PENDING', 'TIMING_CONFIRMED')", name='effect'),
    sa.CheckConstraint("scope IN ('WHOLE_DAY', 'SESSION', 'TIME_RANGE')", name='scope'),
    sa.CheckConstraint('date_to >= date_from', name='date_order'),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('seq'),
    sa.UniqueConstraint('id')
    )
    op.create_index('ix_exceptions_doctor_dates', 'schedule_exceptions', ['doctor_id', 'date_from', 'date_to'], unique=False)
    op.create_table('schedule_templates',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('doctor_id', sa.Text(), nullable=False),
    sa.Column('effective_from', sa.Date(), nullable=False),
    sa.Column('effective_to', sa.Date(), nullable=True),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['doctor_id'], ['doctors.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('doctor_id', 'effective_from', name='template_effective')
    )
    op.create_index(op.f('ix_schedule_templates_doctor_id'), 'schedule_templates', ['doctor_id'], unique=False)
    op.create_table('appointment_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('appointment_id', sa.Text(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('by', sa.Text(), nullable=False),
    sa.Column('change', sa.Text(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_appointment_history_appointment_id'), 'appointment_history', ['appointment_id'], unique=False)
    op.create_table('notifications',
    sa.Column('id', sa.Text(), nullable=False),
    sa.Column('appointment_id', sa.Text(), nullable=False),
    sa.Column('exception_id', sa.Text(), nullable=True),
    sa.Column('trigger', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), server_default='PENDING', nullable=False),
    sa.Column('channel', sa.Text(), nullable=True),
    sa.Column('patient_phone', sa.Text(), nullable=False),
    sa.Column('patient_language', sa.Text(), nullable=True),
    sa.Column('facts', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_by', sa.Text(), nullable=True),
    sa.Column('outcome', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('PENDING', 'SENT', 'FAILED', 'ACKNOWLEDGED')", name='status'),
    sa.CheckConstraint("trigger IN ('SESSION_CANCELLED', 'SESSION_TIME_CHANGED', 'TEMPLATE_CHANGED', 'DESK_MESSAGE')", name='trigger'),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_appointment_id'), 'notifications', ['appointment_id'], unique=False)
    op.create_index(op.f('ix_notifications_exception_id'), 'notifications', ['exception_id'], unique=False)
    op.create_index('ix_notifications_status', 'notifications', ['status'], unique=False)
    op.create_table('template_sessions',
    sa.Column('template_id', sa.Text(), nullable=False),
    sa.Column('template_session_id', sa.Text(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('days_of_week', sa.ARRAY(sa.Text()), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('capacity_model', sa.Text(), nullable=False),
    sa.Column('slot_minutes', sa.Integer(), nullable=True),
    sa.Column('capacity_mode', sa.Text(), nullable=False),
    sa.Column('capacity_value', sa.Integer(), nullable=True),
    sa.Column('walk_in_reserve_percent', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_arrival_offset_minutes', sa.Integer(), server_default='15', nullable=False),
    sa.CheckConstraint("capacity_mode IN ('FIXED', 'PER_HOUR', 'DEFAULT')", name='capacity_mode'),
    sa.CheckConstraint("capacity_model IN ('SEQUENCE', 'TIMED')", name='capacity_model'),
    sa.CheckConstraint('end_time > start_time', name='session_order'),
    sa.CheckConstraint('walk_in_reserve_percent BETWEEN 0 AND 100', name='walk_in_reserve'),
    sa.ForeignKeyConstraint(['template_id'], ['schedule_templates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('template_id', 'template_session_id')
    )


def downgrade() -> None:
    op.drop_table('template_sessions')
    op.drop_index('ix_notifications_status', table_name='notifications')
    op.drop_index(op.f('ix_notifications_exception_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_appointment_id'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_index(op.f('ix_appointment_history_appointment_id'), table_name='appointment_history')
    op.drop_table('appointment_history')
    op.drop_index(op.f('ix_schedule_templates_doctor_id'), table_name='schedule_templates')
    op.drop_table('schedule_templates')
    op.drop_index('ix_exceptions_doctor_dates', table_name='schedule_exceptions')
    op.drop_table('schedule_exceptions')
    op.drop_table('doctor_departments')
    op.drop_index('ix_board_doctor_date', table_name='board_entries')
    op.drop_table('board_entries')
    op.drop_index('uq_appointments_live_slot', table_name='appointments', postgresql_where=sa.text("status IN ('BOOKED', 'CONFIRMED_BY_DESK', 'RESCHEDULED', 'ARRIVED')"))
    op.drop_index('ix_appointments_session', table_name='appointments')
    op.drop_index('ix_appointments_phone', table_name='appointments')
    op.drop_index('ix_appointments_doctor_date', table_name='appointments')
    op.drop_index('ix_appointments_caller_number', table_name='appointments')
    op.drop_table('appointments')
    op.drop_index('ix_lexicon_approved_type', table_name='lexicon_entries')
    op.drop_table('lexicon_entries')
    op.drop_index(op.f('ix_idempotency_keys_created_at'), table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
    op.drop_table('doctors')
    op.drop_table('departments')
    op.drop_table('call_summaries')
