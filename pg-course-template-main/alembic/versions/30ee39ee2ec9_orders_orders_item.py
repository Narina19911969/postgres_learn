"""orders_orders_item

Revision ID: 30ee39ee2ec9
Revises: fe6b95676878
Create Date: 2026-06-17 13:02:50.982507

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '30ee39ee2ec9'
down_revision: Union[str, None] = 'fe6b95676878'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with open(f"alembic/sql/{revision}/up.sql") as file:
        op.execute(file.read())


def downgrade() -> None:
    with open(f"alembic/sql/{revision}/down.sql") as file:
        op.execute(file.read())