"""add lead phone + normalized_phone

Revision ID: 4b2c7d8e9f01
Revises: 3a1f2b9c4d5e
Create Date: 2026-06-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b2c7d8e9f01"
down_revision: Union[str, None] = "3a1f2b9c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("normalized_phone", sa.String(length=32), nullable=True))
    op.create_index("ix_leads_normalized_phone", "leads", ["normalized_phone"])


def downgrade() -> None:
    op.drop_index("ix_leads_normalized_phone", table_name="leads")
    op.drop_column("leads", "normalized_phone")
    op.drop_column("leads", "phone")
