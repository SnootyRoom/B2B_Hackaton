from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.parsers.normalize import (
    delivery_days,
    inn_is_valid,
    local_tz,
    money,
    normalize_method,
    normalize_okpd2,
    normalize_region,
    parse_datetime,
)


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("Томская обл", "Томская область"),
        ("Российская Федерация, 634050, Томская обл, г Томск, пр-кт Ленина", "Томская область"),
        ("г Москва, ул Тверская, д. 1", "Москва"),
        ("Московская область, г Химки", "Московская область"),
        ("г. Санкт-Петербург, Московский пр-кт, д. 5", "Санкт-Петербург"),
        ("Респ Татарстан, г Казань", "Республика Татарстан"),
        ("Республика Алтай, г Горно-Алтайск", "Республика Алтай"),
        ("Алтайский край, г Барнаул", "Алтайский край"),
        ("Ямало-Ненецкий АО, г Салехард", "Ямало-Ненецкий автономный округ"),
        ("Ненецкий АО, г Нарьян-Мар", "Ненецкий автономный округ"),
        ("Ханты-Мансийский Автономный округ - Югра АО", "Ханты-Мансийский автономный округ — Югра"),
        ("Кемеровская область - Кузбасс", "Кемеровская область"),
        ("Респ Саха /Якутия/", "Республика Саха (Якутия)"),
        ("Нижегородской области", "Нижегородская область"),
        ("г Томск", None),
        ("", None),
    ],
)
def test_region(text: str, region: str | None) -> None:
    assert normalize_region(text) == region


def test_inn_checksum() -> None:
    assert inn_is_valid("7707083893")
    assert not inn_is_valid("7707083894")
    assert inn_is_valid("500100732259")
    assert not inn_is_valid("500100732258")
    assert not inn_is_valid("12345")


def test_money() -> None:
    assert money("1 234 567,89") == Decimal("1234567.89")
    assert money("4200000.00") == Decimal("4200000.00")
    assert money("abc") is None
    assert money("-5") is None


def test_datetime() -> None:
    assert parse_datetime("2026-11-05T09:00:00+07:00") == datetime(2026, 11, 5, 2, tzinfo=UTC)
    assert parse_datetime("2026-11-05T09:00:00") == datetime(2026, 11, 5, 6, tzinfo=UTC)
    assert parse_datetime("2026-11-05+03:00") == datetime(2026, 11, 4, 21, tzinfo=UTC)
    assert parse_datetime("05.11.2026 12:00") == datetime(2026, 11, 5, 9, tzinfo=UTC)
    assert parse_datetime("не дата") is None


def test_datetime_in_customer_timezone() -> None:
    """223-ФЗ: время без смещения — местное время заказчика, сдвиг от МСК в часах."""
    krasnoyarsk = local_tz("4")
    assert parse_datetime("2026-11-02T10:00:00", krasnoyarsk) == datetime(
        2026, 11, 2, 3, tzinfo=UTC
    )
    # явное смещение в значении главнее пояса заказчика
    assert parse_datetime("2026-11-02T10:00:00+03:00", krasnoyarsk) == datetime(
        2026, 11, 2, 7, tzinfo=UTC
    )
    assert local_tz(None) == local_tz("0") == local_tz("мусор") == local_tz("15")
    assert parse_datetime("2026-11-02T10:00:00", local_tz(None)) == datetime(
        2026, 11, 2, 7, tzinfo=UTC
    )


def test_method() -> None:
    assert normalize_method("Электронный аукцион") == "auction"
    assert normalize_method("Открытый конкурс в электронной форме") == "contest"
    assert normalize_method("Запрос котировок в электронной форме") == "quotation"
    assert normalize_method("Запрос предложений") == "proposals"
    assert normalize_method("Закупка у единственного поставщика") == "single"
    assert normalize_method("Сбор коммерческих предложений") == "proposals"
    assert normalize_method("Иной способ") == "other"


def test_okpd2() -> None:
    assert normalize_okpd2("62.01.11.000-00000002") == "62.01.11.000"
    assert normalize_okpd2("62.01") == "62.01"
    assert normalize_okpd2("ABC") is None


def test_delivery_days() -> None:
    published = datetime(2026, 10, 20, tzinfo=UTC)
    assert delivery_days("В течение 30 календарных дней", None) == 30
    assert delivery_days("10 (десяти) рабочих дней с даты заключения", None) == 14
    assert delivery_days("до 31.12.2026", published) == 72
    assert delivery_days("По заявке заказчика", published) is None
