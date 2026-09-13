"""Add username, last_name, and language_code on users.

Revision ID: 0003_user_identity
Revises: 0002_message_attachments
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_user_identity"
down_revision: Union[str, Sequence[str], None] = "0002_message_attachments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("username", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("last_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("language_code", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "language_code")
    op.drop_column("users", "last_name")
    op.drop_column("users", "username")
