"""add lead message field

Revision ID: 3a1f2b9c4d5e
Revises: 27e0fffb1a1d
Create Date: 2026-06-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a1f2b9c4d5e"
down_revision: Union[str, None] = "27e0fffb1a1d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("leads", "message")
