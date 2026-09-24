"""위원이 능력단위에 추가로 인정한 시간(granted_hours)

기록 확인이 50% 미만으로 떨어뜨린 단위를, 근거 분석 자료를 보고 위원이
몇 시간까지 인정할지 적는 칸. 요소별 검토 표를 그대로 쓴다 — 기록 확인
판정의 element_id 는 능력단위 코드 10자리다.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("element_review", sa.Column("granted_hours", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("element_review", "granted_hours")
