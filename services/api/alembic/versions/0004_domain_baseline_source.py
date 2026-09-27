"""lexicon rows can come from the domain pack's baseline (docs/architecture/TARGET.md A10)

`frontdesk-api rollout apply` writes the domain's words with source DOMAIN_BASELINE, so a new
pack version can replace them without touching the provider's own rows.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-27
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("source", "lexicon_entries", type_="check")
    op.create_check_constraint(
        "source", "lexicon_entries",
        "source IN ('PROVIDER', 'DOMAIN_BASELINE', 'TRANSCRIPT_MINED', 'AUTO_TRANSLITERATION')",
    )


def downgrade() -> None:
    # Baseline rows stay (the words still work); they are recorded as the provider's again.
    op.execute("UPDATE lexicon_entries SET source = 'PROVIDER' WHERE source = 'DOMAIN_BASELINE'")
    op.drop_constraint("source", "lexicon_entries", type_="check")
    op.create_check_constraint(
        "source", "lexicon_entries", "source IN ('PROVIDER', 'TRANSCRIPT_MINED', 'AUTO_TRANSLITERATION')",
    )
