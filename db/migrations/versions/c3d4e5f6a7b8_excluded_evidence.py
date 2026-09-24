"""위원이 뺀 근거(excluded_evidence) — 깎아 가는 검토 방식

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("element_review", sa.Column("excluded_evidence", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("element_review", "excluded_evidence")
