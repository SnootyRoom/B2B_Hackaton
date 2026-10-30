"""Нормализация значений из извещений: деньги, даты, ИНН, регион, способ, ОКПД2, сроки."""

import math
import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from app.parsers.regions import REGIONS
from app.schemas.procurement import Method, Restriction

# Время в ЕИС без смещения — московское
MSK = timezone(timedelta(hours=3))


def clean_text(value: str | None) -> str | None:
    """Обрезка пробелов, без HTML-тегов; пустая строка → None."""
    if value is None:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def digits(value: str | None) -> str | None:
    if value is None:
        return None
    d = re.sub(r"\D", "", value)
    return d or None


def money(value: str | None) -> Decimal | None:
    """«1 234 567,89» / «1234567.89» → Decimal. Не число → None."""
    if value is None:
        return None
    s = re.sub(r"[\s ₽]|руб\.?", "", value).replace(",", ".")
    try:
        result = Decimal(s)
    except InvalidOperation:
        return None
    return result if result.is_finite() and result >= 0 else None


def parse_datetime(value: str | None) -> datetime | None:
    """ISO-дата или дата-время ЕИС (в т. ч. `2026-11-10+03:00`, `10.11.2026`) → UTC."""
    if not value:
        return None
    s = value.strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?", s)
    if m:
        day, month, year, hh, mm = m.groups()
        dt = datetime(int(year), int(month), int(day), int(hh or 0), int(mm or 0), tzinfo=MSK)
        return dt.astimezone(UTC)
    # xs:date со смещением: 2026-11-10+03:00 / 2026-11-10Z
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(Z|[+-]\d{2}:\d{2})?", s)
    if m:
        s = m.group(1) + "T00:00:00" + (m.group(2) or "")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    return dt.astimezone(UTC)


_INN10 = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _check(d: str, weights: tuple[int, ...]) -> int:
    return sum(int(c) * w for c, w in zip(d, weights, strict=False)) % 11 % 10


def inn_is_valid(inn: str | None) -> bool:
    """Контрольная сумма ИНН: 10 цифр (юрлицо) или 12 (ИП)."""
    if not inn or not inn.isdigit():
        return False
    if len(inn) == 10:
        return _check(inn, _INN10) == int(inn[9])
    if len(inn) == 12:
        return _check(inn, _INN12_1) == int(inn[10]) and _check(inn, _INN12_2) == int(inn[11])
    return False


def normalize_inn(value: str | None) -> str | None:
    inn = digits(value)
    return inn if inn_is_valid(inn) else None


# --- Регион -------------------------------------------------------------------------------

# Особые написания; остальные регионы сопоставляются по основе прилагательного.
_REGION_SPECIAL: dict[str, str] = {
    "Москва": r"\bмоскв[аеы]\b",
    "Санкт-Петербург": r"санкт-петербург|\bспб\b",
    "Севастополь": r"севастопол",
    "Республика Адыгея": r"адыге",
    "Республика Алтай": r"респ\w*\.?\s+алтай\b|\bалтай\s+респ",
    "Республика Башкортостан": r"башкорт",
    "Республика Бурятия": r"бурят",
    "Республика Дагестан": r"дагестан",
    "Республика Ингушетия": r"ингушет",
    "Республика Калмыкия": r"калмык",
    "Республика Карелия": r"карели",
    "Республика Коми": r"\bкоми\b",
    "Республика Крым": r"\bкрым\b",
    "Республика Марий Эл": r"марий\s+эл",
    "Республика Мордовия": r"мордов",
    "Республика Саха (Якутия)": r"\bсаха\b|якути",
    "Республика Северная Осетия — Алания": r"осети",
    "Республика Татарстан": r"татарстан",
    "Республика Тыва": r"\bтыва\b",
    "Республика Хакасия": r"хакаси",
    "Удмуртская Республика": r"удмурт",
    "Чеченская Республика": r"чечен",
    "Чувашская Республика": r"чуваш",
    "Кабардино-Балкарская Республика": r"кабардино",
    "Карачаево-Черкесская Республика": r"карачаево",
    "Донецкая Народная Республика": r"донецк|\bднр\b",
    "Луганская Народная Республика": r"луганск|\bлнр\b",
    "Кемеровская область": r"кемеровск\w*\s+обл|кузбасс",
    "Ханты-Мансийский автономный округ — Югра": r"ханты-мансийск\w*\s+(авт|ао)|\bюгра\b|\bхмао\b",
    "Ямало-Ненецкий автономный округ": r"ямало-ненец|\bянао\b",
    "Ненецкий автономный округ": r"(?<!ямало-)\bненецк",
}

_ADJ_ENDINGS = r"(?:ая|ой|ую|ий|ого|ом|ому|ое)\b"


def _region_patterns() -> list[tuple[re.Pattern[str], str]]:
    result = []
    for region in REGIONS:
        if region in _REGION_SPECIAL:
            pattern = _REGION_SPECIAL[region]
        else:
            # «Томская область» → «томск» + окончание прилагательного: не путается с «г Томск»
            stem = region.split()[0].lower()[:-2]
            pattern = r"\b" + re.escape(stem) + _ADJ_ENDINGS
        result.append((re.compile(pattern), region))
    return result


_REGIONS_RE = _region_patterns()


def normalize_region(text: str | None) -> str | None:
    """Адрес или название региона → субъект РФ из справочника.

    Адреса пишутся от крупного к мелкому, поэтому берётся самое раннее совпадение:
    «Санкт-Петербург, Московский пр-кт» → Санкт-Петербург.
    """
    if not text:
        return None
    s = text.lower().replace("ё", "е").replace("–", "-").replace("—", "-")
    best: tuple[int, str] | None = None
    for pattern, region in _REGIONS_RE:
        m = pattern.search(s)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), region)
    return best[1] if best else None


# --- Способ закупки, ограничения, ОКПД2, сроки --------------------------------------------

_METHODS: list[tuple[str, Method]] = [
    ("единствен", Method.single),
    ("котиров", Method.quotation),
    ("предложени", Method.proposals),
    ("конкурс", Method.contest),
    ("аукцион", Method.auction),
]


def normalize_method(raw: str | None) -> Method | None:
    if not raw:
        return None
    s = raw.lower()
    for key, method in _METHODS:
        if key in s:
            return method
    return Method.other


# В 44-ФЗ ограничения часто записаны только ссылкой на статью: ч. 3 ст. 30 — закупка у СМП
# и СОНКО, ст. 28 — УИС, ст. 29 — организации инвалидов, ст. 14 — национальный режим.
_RESTRICTIONS: list[tuple[str, Restriction]] = [
    (
        r"мал\w+ (и средн\w+ )?предпринимательств|\bсмп\b|социально ориентированн"
        r"|ч\.\s*3\s+ст\.\s*30\b",
        Restriction.smp_only,
    ),
    (r"уголовно-исполнительн|ст(\.|ать\w+)\s*28\b", Restriction.prefs_uis),
    (r"инвалид|ст(\.|ать\w+)\s*29\b", Restriction.prefs_disabled),
    (
        r"иностранн|национальн\w+ режим|запрет на допуск|ограничени\w+ допуска"
        r"|ст(\.|ать\w+)\s*14\b",
        Restriction.national_regime,
    ),
]


def normalize_restrictions(texts: list[str]) -> list[Restriction]:
    """Тексты требований/преимуществ/запретов → коды ограничений без дублей."""
    result: list[Restriction] = []
    for text in texts:
        s = text.lower()
        found = next((r for pattern, r in _RESTRICTIONS if re.search(pattern, s)), None)
        code = found or Restriction.other
        if code not in result:
            result.append(code)
    return result


def normalize_okpd2(value: str | None) -> str | None:
    """«62.01.11.000-00000001» (КТРУ) → «62.01.11.000»; не код ОКПД2 → None."""
    if not value:
        return None
    code = value.strip().split("-")[0]
    return code if re.fullmatch(r"\d{2}(\.\d{1,3}){0,3}", code) else None


_DAYS_RE = re.compile(
    r"(\d{1,4})\s*(?:\(\s*[а-яё\s-]+\)\s*)?(календарн\w*|рабоч\w*)?\s*(?:дн|ден|сут)", re.I
)
_UNTIL_DATE_RE = re.compile(r"(?:по|до|не позднее)\s+(\d{2}\.\d{2}\.\d{4})")


def delivery_days(text: str | None, published_at: datetime | None) -> int | None:
    """Срок поставки в днях: «в течение 30 календарных дней», «10 (десяти) рабочих дней»,
    «до 31.12.2026» (от даты размещения). Не распознан → None."""
    if not text:
        return None
    m = _DAYS_RE.search(text)
    if m:
        n = int(m.group(1))
        if m.group(2) and m.group(2).lower().startswith("рабоч"):
            n = math.ceil(n * 7 / 5)
        return n
    m = _UNTIL_DATE_RE.search(text)
    if m and published_at is not None:
        try:
            until = datetime.strptime(m.group(1), "%d.%m.%Y").date()
        except ValueError:
            return None
        days = (until - published_at.astimezone(MSK).date()).days
        return days if days >= 0 else None
    return None


def percent(value: str | None) -> Decimal | None:
    """«10.0», «5% от начальной (максимальной) цены» → процент; сумма без знака % → None."""
    if not value:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", value)
    number = money(m.group(1)) if m else money(value)
    return number if number is not None and number <= 100 else None


def security_amount(
    amount: Decimal | None, pct: Decimal | None, nmck: Decimal
) -> tuple[Decimal | None, Decimal | None]:
    """Обеспечение в рублях и процентах НМЦК.

    Процент главнее суммы: в совместных закупках сумма в документе — доля одного заказчика,
    а процент общий. Нет процента → считается по сумме.
    """
    if pct is not None:
        amount = (nmck * pct / 100).quantize(Decimal("0.01"))
    elif amount is not None and nmck:
        pct = (amount / nmck * 100).quantize(Decimal("0.01"))
    return amount, pct
