"""Store attachment metadata on messages so photos can be re-sent to the LLM.

Revision ID: 0002_message_attachments
Revises: 0001_stage3_schema
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_message_attachments"
down_revision: Union[str, Sequence[str], None] = "0001_stage3_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("attachments", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "attachments")
