"""template base: от какого профиля построен профиль из шаблона

Revision ID: 0003_template_base
Revises: 0002_multiple_profiles
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_template_base"
down_revision: str | None = "0002_multiple_profiles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scoring_profiles", sa.Column("template_base_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "scoring_profiles_template_base_id_fkey",
        "scoring_profiles",
        "scoring_profiles",
        ["template_base_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "scoring_profiles_template_base_id_fkey", "scoring_profiles", type_="foreignkey"
    )
    op.drop_column("scoring_profiles", "template_base_id")
