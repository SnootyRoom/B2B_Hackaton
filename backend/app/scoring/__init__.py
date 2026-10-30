"""Движок скоринга (роль 3). Контракты входа и выхода — app.schemas.scoring / app.schemas.score."""

from app.scoring.defaults import default_profile, with_defaults
from app.scoring.engine import Similarity, score
from app.scoring.fields import extract_fields

__all__ = ["Similarity", "default_profile", "extract_fields", "score", "with_defaults"]
