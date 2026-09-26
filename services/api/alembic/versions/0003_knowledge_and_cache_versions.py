"""knowledge base entries and cache version stamps (docs/architecture/TARGET.md A4, A5)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("questions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("action", sa.Text(), nullable=False, server_default="ANSWER"),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source", sa.Text(), nullable=False, server_default="PROVIDER"),
        sa.Column("updated_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("action IN ('ANSWER', 'TRANSFER_DESK')", name="knowledge_action"),
        sa.CheckConstraint("source IN ('PROVIDER', 'DOCUMENT')", name="knowledge_source"),
        sa.CheckConstraint("action <> 'TRANSFER_DESK' OR destination IS NOT NULL", name="knowledge_destination"),
    )
    op.create_index("ix_knowledge_approved_topic", "knowledge_entries", ["approved", "topic"])
    # One row per cached data set. Writers bump `version` in the same transaction as the change;
    # every replica compares it with the version its in-process cache was built from.
    op.create_table(
        "cache_versions",
        sa.Column("name", sa.Text(), primary_key=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.execute("INSERT INTO cache_versions (name) VALUES ('directory'), ('knowledge')")


def downgrade() -> None:
    op.drop_table("cache_versions")
    op.drop_index("ix_knowledge_approved_topic", table_name="knowledge_entries")
    op.drop_table("knowledge_entries")
