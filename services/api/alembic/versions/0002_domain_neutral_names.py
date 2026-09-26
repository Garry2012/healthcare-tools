"""domain-neutral names (docs/architecture/TARGET.md A2)

doctor → resource, department → category, appointment → booking, patient → customer,
fee → price, symptom route → need route. Data is kept: tables and columns are renamed in
place, enum values and JSON keys are rewritten, lexicon ids are recomputed from the new
concept types, and doctor-only columns move into `resources.attributes`. Healthcare-only enum
values that merge into one neutral value keep the original (call intent in
`tool_outcomes.legacyIntent`, exception reason as a `[was X]` note prefix), so downgrade
restores them exactly. Stored ids (`doc_*`, `dept_*`) are unchanged; a demo database needs
`seed --reset` afterwards (the seed refuses to mix old and new demo ids).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

TABLES = (  # old, new
    ("doctors", "resources"),
    ("departments", "categories"),
    ("doctor_departments", "resource_categories"),
    ("appointments", "bookings"),
    ("appointment_history", "booking_history"),
)
COLUMNS = (  # table (new name), old column, new column
    ("categories", "has_consultant", "offers_bookings"),
    ("resources", "fee_amount", "price_amount"),
    ("resources", "fee_currency", "price_currency"),
    ("resources", "fee_confirmed", "price_confirmed"),
    ("resource_categories", "doctor_id", "resource_id"),
    ("resource_categories", "department_id", "category_id"),
    ("schedule_templates", "doctor_id", "resource_id"),
    ("schedule_exceptions", "doctor_id", "resource_id"),
    ("schedule_exceptions", "impact_appointments", "impact_bookings"),
    ("board_entries", "doctor_id", "resource_id"),
    ("bookings", "doctor_id", "resource_id"),
    ("bookings", "department_id", "category_id"),
    ("bookings", "patient_name", "customer_name"),
    ("bookings", "patient_name_normalized", "customer_name_normalized"),
    ("booking_history", "appointment_id", "booking_id"),
    ("notifications", "appointment_id", "booking_id"),
    ("notifications", "patient_phone", "customer_phone"),
    ("notifications", "patient_language", "customer_language"),
    ("call_summaries", "appointment_id", "booking_id"),
)
VALUES = (  # table, column, old value, new value
    ("resources", "booking_policy", "NO_OPD", "NOT_OFFERED"),
    ("lexicon_entries", "concept_type", "DEPARTMENT", "CATEGORY"),
    ("lexicon_entries", "concept_type", "DOCTOR", "RESOURCE"),
    ("lexicon_entries", "concept_type", "SYMPTOM_ROUTE", "NEED_ROUTE"),
    ("lexicon_entries", "source", "HOSPITAL", "PROVIDER"),
    ("bookings", "status", "CANCELLED_BY_PATIENT", "CANCELLED_BY_CUSTOMER"),
    ("bookings", "status", "CANCELLED_BY_HOSPITAL", "CANCELLED_BY_PROVIDER"),
    ("booking_history", "change", "CANCELLED_BY_PATIENT", "CANCELLED_BY_CUSTOMER"),
    ("booking_history", "change", "CANCELLED_BY_HOSPITAL", "CANCELLED_BY_PROVIDER"),
    ("schedule_exceptions", "reason_category", "SURGERY", "OTHER_DUTY"),
    ("schedule_exceptions", "reason_category", "EMERGENCY_DUTY", "OTHER_DUTY"),
    ("schedule_exceptions", "reason_category", "CONFERENCE", "EVENT"),
    ("call_summaries", "intent", "LAB", "SERVICE_TRANSFER"),
    ("call_summaries", "intent", "PHARMACY", "SERVICE_TRANSFER"),
    ("call_summaries", "intent", "INSURANCE", "SERVICE_TRANSFER"),
    ("call_summaries", "intent", "SYMPTOM_ROUTING", "NEED_ROUTING"),
    ("call_summaries", "outcome", "APPOINTMENT_BOOKED", "BOOKING_CREATED"),
    ("call_summaries", "outcome", "APPOINTMENT_CANCELLED", "BOOKING_CANCELLED"),
    ("call_summaries", "outcome", "APPOINTMENT_RESCHEDULED", "BOOKING_RESCHEDULED"),
)
FACT_KEYS = (
    ("doctorId", "resourceId"),
    ("doctorName", "resourceName"),
    ("appointmentDate", "bookingDate"),
    ("appointmentStatus", "bookingStatus"),
)
STATUSES = "'BOOKED', 'CONFIRMED_BY_DESK', 'RESCHEDULED', 'NEEDS_RESCHEDULE', 'ARRIVED', 'COMPLETED', 'NO_SHOW'"
CHECKS_NEW = (
    ("resources", "policy", "booking_policy IN ('BOOKABLE', 'DESK_ONLY', 'NOT_OFFERED')"),
    ("lexicon_entries", "concept_type",
     "concept_type IN ('CATEGORY', 'RESOURCE', 'NEED_ROUTE', 'RED_FLAG', 'DAY_PART', 'SERVICE_TRANSFER')"),
    ("lexicon_entries", "source", "source IN ('PROVIDER', 'TRANSCRIPT_MINED', 'AUTO_TRANSLITERATION')"),
    ("bookings", "status", f"status IN ({STATUSES}, 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_PROVIDER')"),
)
CHECKS_OLD = (
    ("resources", "policy", "booking_policy IN ('BOOKABLE', 'DESK_ONLY', 'NO_OPD')"),
    ("lexicon_entries", "concept_type",
     "concept_type IN ('DEPARTMENT', 'DOCTOR', 'SYMPTOM_ROUTE', 'RED_FLAG', 'DAY_PART', 'SERVICE_TRANSFER')"),
    ("lexicon_entries", "source", "source IN ('HOSPITAL', 'TRANSCRIPT_MINED', 'AUTO_TRANSLITERATION')"),
    ("bookings", "status", f"status IN ({STATUSES}, 'CANCELLED_BY_PATIENT', 'CANCELLED_BY_HOSPITAL')"),
)
# Same formula as services.directory.lexicon_id.
LEXICON_ID = (
    "UPDATE lexicon_entries SET id = 'lex_' || left(encode(sha256(convert_to("
    "concept_type || '|' || concept_id || '|' || term || '|' || language, 'UTF8')), 'hex'), 16)"
)


def _rename_objects(pairs: tuple[tuple[str, str], ...]) -> None:
    """Rename every index and constraint whose name contains an old word (cosmetic, but keeps
    `\\d` output and error messages in the new vocabulary)."""
    replaces = "name"
    for old, new in pairs:
        replaces = f"replace({replaces}, '{old}', '{new}')"
    op.execute(f"""
DO $$
DECLARE r record; target text;
BEGIN
  FOR r IN SELECT c.conname AS name, c.conrelid::regclass::text AS tbl FROM pg_constraint c
           WHERE c.connamespace = 'public'::regnamespace AND c.contype IN ('p', 'f', 'u') LOOP
    target := (SELECT {replaces} FROM (SELECT r.name AS name) x);
    IF target <> r.name THEN
      EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I', r.tbl, r.name, target);
    END IF;
  END LOOP;
  FOR r IN SELECT i.relname AS name FROM pg_class i
           WHERE i.relnamespace = 'public'::regnamespace AND i.relkind = 'i' LOOP
    target := (SELECT {replaces} FROM (SELECT r.name AS name) x);
    IF target <> r.name AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = target) THEN
      EXECUTE format('ALTER INDEX %I RENAME TO %I', r.name, target);
    END IF;
  END LOOP;
END $$;
""")


def _swap_checks(checks: tuple[tuple[str, str, str], ...]) -> None:
    for table, name, _ in checks:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")


def _add_checks(checks: tuple[tuple[str, str, str], ...]) -> None:
    for table, name, expression in checks:
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expression})")


def _rewrite_facts(pairs: tuple[tuple[str, str], ...]) -> None:
    for old, new in pairs:
        op.execute(
            f"UPDATE notifications SET facts = (facts - '{old}') || jsonb_build_object('{new}', facts -> '{old}') "
            f"WHERE facts ? '{old}'"
        )


def upgrade() -> None:
    for old, new in TABLES:
        op.rename_table(old, new)
    for table, old, new in COLUMNS:
        op.alter_column(table, old, new_column_name=new)

    # Doctor-only facts become domain-pack attributes.
    op.execute("ALTER TABLE resources ADD COLUMN attributes jsonb NOT NULL DEFAULT '{}'::jsonb")
    op.execute(
        "UPDATE resources SET attributes = jsonb_strip_nulls(jsonb_build_object("
        "'qualification', qualification, 'yearsOfExperience', years_of_experience))"
    )
    op.execute("ALTER TABLE resources DROP COLUMN qualification, DROP COLUMN years_of_experience")

    op.execute(
        "UPDATE call_summaries SET tool_outcomes = tool_outcomes || jsonb_build_object('legacyIntent', intent) "
        "WHERE intent IN ('LAB', 'PHARMACY', 'INSURANCE')"
    )
    op.execute(
        "UPDATE schedule_exceptions SET note = '[was ' || reason_category || '] ' || coalesce(note, '') "
        "WHERE reason_category IN ('SURGERY', 'EMERGENCY_DUTY')"
    )
    _swap_checks(CHECKS_OLD)
    op.execute("ALTER TABLE lexicon_entries ALTER COLUMN source SET DEFAULT 'PROVIDER'")
    for table, column, old, new in VALUES:
        op.execute(f"UPDATE {table} SET {column} = '{new}' WHERE {column} = '{old}'")
    _add_checks(CHECKS_NEW)
    op.execute(LEXICON_ID)
    _rewrite_facts(FACT_KEYS)
    op.execute(
        "UPDATE notifications SET facts = jsonb_set(facts, '{bookingStatus}', "
        "to_jsonb(replace(replace(facts ->> 'bookingStatus', 'CANCELLED_BY_PATIENT', 'CANCELLED_BY_CUSTOMER'), "
        "'CANCELLED_BY_HOSPITAL', 'CANCELLED_BY_PROVIDER'))) WHERE facts ? 'bookingStatus'"
    )
    # Stored responses use the old wire names; a replay must never return them.
    op.execute("DELETE FROM idempotency_keys")
    _rename_objects((("appointment", "booking"), ("doctor", "resource"), ("departments", "categories"),
                     ("department", "category"),
                     ("patient", "customer")))


def downgrade() -> None:
    _rename_objects((("booking", "appointment"), ("resource", "doctor"), ("categories", "departments"),
                     ("category", "department"),
                     ("customer", "patient")))
    op.execute("DELETE FROM idempotency_keys")
    _rewrite_facts(tuple((new, old) for old, new in FACT_KEYS))
    op.execute(
        "UPDATE notifications SET facts = jsonb_set(facts, '{appointmentStatus}', "
        "to_jsonb(replace(replace(facts ->> 'appointmentStatus', 'CANCELLED_BY_CUSTOMER', 'CANCELLED_BY_PATIENT'), "
        "'CANCELLED_BY_PROVIDER', 'CANCELLED_BY_HOSPITAL'))) WHERE facts ? 'appointmentStatus'"
    )
    _swap_checks(CHECKS_NEW)
    # Merged values map to the first here; the exact originals are restored from what upgrade kept, below.
    seen: set[tuple[str, str, str]] = set()
    for table, column, old, new in VALUES:
        if (table, column, new) in seen:
            continue
        seen.add((table, column, new))
        op.execute(f"UPDATE {table} SET {column} = '{old}' WHERE {column} = '{new}'")
    op.execute(
        "UPDATE call_summaries SET intent = tool_outcomes ->> 'legacyIntent', tool_outcomes = tool_outcomes - "
        "'legacyIntent' WHERE tool_outcomes ? 'legacyIntent'"
    )
    op.execute(
        "UPDATE schedule_exceptions SET reason_category = substring(note from '^\\[was ([A-Z_]+)\\] '), "
        "note = nullif(regexp_replace(note, '^\\[was [A-Z_]+\\] ', ''), '') WHERE note ~ '^\\[was [A-Z_]+\\] '"
    )
    op.execute("ALTER TABLE lexicon_entries ALTER COLUMN source SET DEFAULT 'HOSPITAL'")
    _add_checks(CHECKS_OLD)
    op.execute(LEXICON_ID)

    op.execute("ALTER TABLE resources ADD COLUMN qualification text, ADD COLUMN years_of_experience integer")
    op.execute(
        "UPDATE resources SET qualification = attributes ->> 'qualification', "
        "years_of_experience = (attributes ->> 'yearsOfExperience')::integer"
    )
    op.execute("ALTER TABLE resources DROP COLUMN attributes")

    for table, old, new in reversed(COLUMNS):
        op.alter_column(table, new, new_column_name=old)
    for old, new in reversed(TABLES):
        op.rename_table(new, old)
