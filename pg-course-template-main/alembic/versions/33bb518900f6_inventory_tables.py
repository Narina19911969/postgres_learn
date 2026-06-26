"""inventory_tables

Revision ID: 33bb518900f6
Revises: a64cb59b105b
Create Date: 2026-06-25 14:10:07.255640

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33bb518900f6'
down_revision: Union[str, None] = 'a64cb59b105b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with open(f"alembic/sql/{revision}/up.sql") as file:
        op.execute(file.read())


def downgrade() -> None:
    with open(f"alembic/sql/{revision}/down.sql") as file:
        op.execute(file.read())