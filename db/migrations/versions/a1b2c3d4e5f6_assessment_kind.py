"""assessment.kind — 시간 대조(time)와 근거 분석(evidence)을 구분한다

Revision ID: a1b2c3d4e5f6
Revises: 6c13f6340ab5
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '6c13f6340ab5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assessment", sa.Column(
        "kind", sa.String(10), nullable=False, server_default="evidence"))
    # 기존 행 채우기 — 시간 대조는 model='deterministic' 으로만 기록돼 왔다.
    op.execute("UPDATE assessment SET kind='time' WHERE model='deterministic'")
    op.create_index("ix_assessment_kind", "assessment", ["kind"])


def downgrade() -> None:
    op.drop_index("ix_assessment_kind", table_name="assessment")
    op.drop_column("assessment", "kind")
