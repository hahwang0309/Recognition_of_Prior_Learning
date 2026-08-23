"""전문가 검토 5단계 — 보완 항목 결과와 단계 표시

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "remediation_result",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("assessment_id", sa.Integer,
                  sa.ForeignKey("assessment.id", ondelete="CASCADE"), index=True),
        sa.Column("item_key", sa.String(16), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("item", sa.Text, nullable=False),
        sa.Column("result", sa.String(8), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("decided_by", sa.String(60)),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("assessment_id", "item_key", name="uq_remediation_item"),
    )
    # 어느 단계까지 왔나. 1 인정검토 · 2 추가서류 · 3 면접 · 4 실기 · 5 최종
    op.add_column("assessment", sa.Column(
        "review_stage", sa.SmallInteger, nullable=False, server_default="1"))


def downgrade() -> None:
    op.drop_column("assessment", "review_stage")
    op.drop_table("remediation_result")
