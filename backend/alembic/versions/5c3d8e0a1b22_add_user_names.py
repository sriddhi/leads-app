"""add user first_name + last_name

Revision ID: 5c3d8e0a1b22
Revises: 4b2c7d8e9f01
Create Date: 2026-06-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5c3d8e0a1b22"
down_revision: Union[str, None] = "4b2c7d8e9f01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("first_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=100), nullable=True))
    # Backfill from full_name: first token -> first_name, remainder -> last_name.
    op.execute("UPDATE users SET first_name = split_part(full_name, ' ', 1) "
               "WHERE first_name IS NULL")
    op.execute("UPDATE users SET last_name = NULLIF(substr(full_name, "
               "length(split_part(full_name, ' ', 1)) + 2), '') WHERE last_name IS NULL")


def downgrade() -> None:
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
