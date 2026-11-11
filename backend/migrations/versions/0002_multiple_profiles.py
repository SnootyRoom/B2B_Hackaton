"""multiple profiles: один активный, уникальное имя, версии оценки

Revision ID: 0002_multiple_profiles
Revises: 69f0d7bc983e
Create Date: 2026-11-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_multiple_profiles"
down_revision: str | None = "69f0d7bc983e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Данные: у пользователя оставить активным только самый свежий профиль
    op.execute(
        """
        UPDATE scoring_profiles SET is_active = false
        WHERE is_active AND id NOT IN (
            SELECT DISTINCT ON (owner_id) id FROM scoring_profiles
            WHERE is_active ORDER BY owner_id, updated_at DESC
        )
        """
    )
    # Данные: повторяющиеся имена → «<имя> (<часть id>)», кроме самого свежего
    op.execute(
        """
        UPDATE scoring_profiles p SET name = left(p.name, 180) || ' (' || left(p.id::text, 8) || ')'
        FROM (
            SELECT id, row_number() OVER (
                PARTITION BY owner_id, name ORDER BY is_active DESC, updated_at DESC
            ) AS rn
            FROM scoring_profiles
        ) d
        WHERE d.id = p.id AND d.rn > 1
        """
    )
    op.create_unique_constraint(
        "uq_scoring_profiles_owner_name", "scoring_profiles", ["owner_id", "name"]
    )
    op.create_index(
        "uq_scoring_profiles_one_active",
        "scoring_profiles",
        ["owner_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    # Старые оценки без версий считаются устаревшими и досчитаются при переключении
    op.add_column("score_results", sa.Column("profile_version", sa.String(32), nullable=True))
    op.add_column("score_results", sa.Column("engine_version", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("score_results", "engine_version")
    op.drop_column("score_results", "profile_version")
    op.drop_index("uq_scoring_profiles_one_active", table_name="scoring_profiles")
    op.drop_constraint("uq_scoring_profiles_owner_name", "scoring_profiles", type_="unique")
