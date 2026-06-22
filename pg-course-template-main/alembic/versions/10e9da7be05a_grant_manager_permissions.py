"""grant_manager_permissions

Revision ID: 10e9da7be05a
Revises: 30ee39ee2ec9
Create Date: 2026-06-22 15:14:59.372804

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '10e9da7be05a'
down_revision: Union[str, None] = '30ee39ee2ec9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with open(f"alembic/sql/{revision}/up.sql") as file:
        op.execute(file.read())


def downgrade() -> None:
    with open(f"alembic/sql/{revision}/down.sql") as file:
        op.execute(file.read())