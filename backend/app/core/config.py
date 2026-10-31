from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://app:app@db:5432/app"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str = "change-me"
    jwt_ttl_hours: int = 12
    cookie_name: str = "access_token"
    cookie_secure: bool = False

    demo_user_email: str = "demo@example.com"
    demo_user_password: str = "demo12345"

    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_folder_id: str = ""  # YandexGPT: каталог Yandex Cloud

    dadata_api_key: str = ""
    egrul_cache_ttl_days: int = 7

    upload_max_file_mb: int = 20
    upload_max_archive_mb: int = 100
    upload_max_files: int = 500
    upload_dir: Path = Path("/data/uploads")

    # Каталоги данных из репозитория (монтируются в контейнер)
    customers_dir: Path = Path("/repo/data/customers")
    demo_dir: Path = Path("/repo/data/demo")

    # Пороги semantic_match: калибруются ролью 3, в коде не хардкодятся
    # e5 сжимает близость в 0,78–0,89; пороги подобраны scripts/calibrate.py
    # на tests/dataset/scenarios_draft.yaml (проверка — scenarios_holdout.yaml)
    semantic_c0: float = 0.82
    semantic_c1: float = 0.86
    # Балл группы «Соответствие» ниже этого — предмет не тот, итог не выше «Пропустить»
    fit_min: float = 50.0
    # Близость по смыслу, с которой предмет считается своим, даже если код ОКПД2 не совпал:
    # в справочнике может не быть категории компании. Строже semantic_c1 — смежные предметы ниже
    semantic_lift: float = 0.88
    # Важность несовпавшего кода ОКПД2, если предмет проверен и по смыслу: кода деятельности могло
    # не быть в справочнике категорий. 0 — код только подтверждает, 3 — штраф в полную силу.
    # Подобрано scripts/calibrate.py по пяти наборам роли 2 (3 → 88,5%, 2 → 91,8%)
    okpd2_miss_weight: float = 2.0
    # Сумма за границей диапазона профиля больше чем во столько раз — итог не выше «Пропустить»
    money_far_factor: float = 2.0

    # Тесты: выполнять задачи Celery синхронно, без брокера
    celery_eager: bool = False

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
