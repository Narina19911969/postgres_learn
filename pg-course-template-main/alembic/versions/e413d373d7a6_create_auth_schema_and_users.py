"""create_auth_schema_and_users

Revision ID: e413d373d7a6
Revises: 10e9da7be05a
Create Date: 2026-06-22 15:47:04.367363

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e413d373d7a6'
down_revision: Union[str, None] = '10e9da7be05a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with open(f"alembic/sql/{revision}/up.sql") as file:
        op.execute(file.read())


def downgrade() -> None:
    with open(f"alembic/sql/{revision}/down.sql") as file:
        op.execute(file.read())