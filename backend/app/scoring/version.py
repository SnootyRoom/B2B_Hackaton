"""Версии оценки: по ним понятно, актуальна ли сохранённая оценка (задача A).

profile_version — хэш правил, весов и порогов профиля (имя и описание не входят:
переименование не требует пересчёта). engine_version — ревизия движка и его настройки.
Совпали обе и закупка не менялась после расчёта — пересчитывать не нужно.
"""

import hashlib
import json

from app.core.config import get_settings
from app.schemas.scoring import ScoringProfileData

# Поднять при изменении логики движка, меняющей оценки: старые оценки станут устаревшими
ENGINE_REVISION = "1"

_ENGINE_SETTINGS = (
    "semantic_c0",
    "semantic_c1",
    "semantic_lift",
    "fit_min",
    "okpd2_miss_weight",
    "money_far_factor",
)


def _digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def profile_version(profile: ScoringProfileData) -> str:
    return _digest(
        profile.model_dump(mode="json", include={"rules", "group_weights", "thresholds"})
    )


def engine_version() -> str:
    s = get_settings()
    return _digest([ENGINE_REVISION, *(getattr(s, name) for name in _ENGINE_SETTINGS)])
