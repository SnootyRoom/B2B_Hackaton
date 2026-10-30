from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.errors import ParseError
from app.parsers.registry import parse_file
from app.schemas.common import ErrorCode

FIXTURES = Path(__file__).parent / "fixtures"


def _parse(name: str) -> list:  # type: ignore[type-arg]
    return parse_file((FIXTURES / name).read_bytes(), name)


def test_44_ef2020_reference() -> None:
    [p] = _parse("notice44_ef2020.xml")
    assert p.parsed_by == "adapter:eis44"
    assert p.reg_number == "0365200000026000123"
    assert p.lot_number is None
    assert p.law == "44"
    assert p.subject == "Оказание услуг по сопровождению программного обеспечения"
    assert p.nmck == Decimal("4200000.00")
    assert p.currency == "RUB"
    assert p.method == "auction"
    assert p.method_raw == "Электронный аукцион"
    assert p.customer_inn == "7707083893"  # размещает сам заказчик (responsibleRole=CU)
    assert p.customer_name and p.customer_name.startswith("ОБЛАСТНОЕ")
    assert p.region == "Томская область"
    assert p.delivery_place and "ул Фрунзе" in p.delivery_place
    assert p.published_at == datetime(2026, 10, 20, 3, 15, tzinfo=UTC)
    assert p.application_deadline == datetime(2026, 11, 5, 2, 0, tzinfo=UTC)
    assert p.delivery_days == 30
    assert p.okpd2_codes == ["62.02.30.000", "62.01.11.000"]
    assert [i.name for i in p.items] == [
        "Сопровождение информационной системы",
        "Доработка модулей",
    ]
    assert p.items[0].quantity == 2 and p.items[0].unit == "Условная единица"
    assert p.bid_security == Decimal("42000.00") and p.bid_security_pct == Decimal("1.00")
    assert p.contract_security == Decimal("420000.00") and p.contract_security_pct == 10
    assert p.restrictions == ["smp_only"]
    assert p.source_url and "regNumber=0365200000026000123" in p.source_url


def test_223_multilot_reference() -> None:
    lots = _parse("notice223_multilot.xml")
    assert [p.reg_number for p in lots] == ["32616481510-1", "32616481510-2"]
    first, second = lots
    assert first.parsed_by == "adapter:eis223"
    assert first.law == "223"
    assert first.lot_number == 1
    assert first.subject == "Монтаж кровли склада"
    assert first.nmck == Decimal("12500000.50")
    assert first.method == "auction"
    assert first.customer_inn == "7736050003"
    assert first.customer_name == 'АКЦИОНЕРНОЕ ОБЩЕСТВО "СТРОЙЗАКАЗЧИК"'
    assert first.region == "Красноярский край"
    assert first.application_deadline == datetime(2026, 11, 12, 7, 0, tzinfo=UTC)
    assert first.okpd2_codes == ["43.91.19.110"]
    assert first.items[0].name == "Работы кровельные"
    assert first.items[0].quantity == 1500
    assert first.restrictions == ["smp_only"]
    # Общие поля извещения копируются в каждый лот; регион без места поставки — по адресу заказчика
    assert second.nmck == Decimal("3000000.00")
    assert second.customer_inn == first.customer_inn
    assert second.region == "Красноярский край"
    assert second.restrictions == []


def test_unknown_format_goes_to_universal() -> None:
    [p] = _parse("notice615_unknown.xml")
    assert p.parsed_by == "universal"
    assert p.law == "615"
    assert p.reg_number == "2041300000126000045"
    assert p.subject == "Капитальный ремонт крыши многоквартирного дома"
    assert p.nmck == Decimal("8750000.00")
    assert p.method == "auction"
    assert p.customer_inn == "7707083893"
    assert p.region == "Республика Татарстан"
    assert p.application_deadline == datetime(2026, 11, 14, 21, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("protocol.xml", (FIXTURES / "protocol44.xml").read_bytes(), ErrorCode.NOT_A_NOTICE),
        (
            "no_price.xml",
            (FIXTURES / "notice44_no_price.xml").read_bytes(),
            ErrorCode.MISSING_REQUIRED_FIELD,
        ),
        ("broken.xml", b"<notice><unclosed>", ErrorCode.UNSUPPORTED_FORMAT),
        ("empty.xml", b"", ErrorCode.UNSUPPORTED_FORMAT),
        ("doc.pdf", b"%PDF-1.4", ErrorCode.UNSUPPORTED_FORMAT),
        ("other.xml", b"<root><a>1</a></root>", ErrorCode.NOT_A_NOTICE),
        # файл заказчика по ошибке загружен как закупка
        ("0275066119.json", b'{"inn": "0275066119", "name": "OOO"}', ErrorCode.NOT_A_NOTICE),
        ("no_price.json", b'{"reg_number": "1", "subject": "x"}', ErrorCode.MISSING_REQUIRED_FIELD),
    ],
)
def test_errors(name: str, content: bytes, code: ErrorCode) -> None:
    with pytest.raises(ParseError) as e:
        parse_file(content, name)
    assert e.value.code == code


def test_missing_field_message() -> None:
    with pytest.raises(ParseError) as e:
        _parse("notice44_no_price.xml")
    assert e.value.message == "В файле не найдено: НМЦК"


def test_xxe_is_not_resolved(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE n [<!ENTITY x SYSTEM "file://{secret}">]>'
        "<notice><purchaseNumber>0365200000026000123</purchaseNumber>"
        "<purchaseObjectInfo>&x;Поставка</purchaseObjectInfo><maxPrice>1</maxPrice></notice>"
    ).encode()
    [p] = parse_file(xml, "x.xml")
    assert "TOP-SECRET" not in p.subject
