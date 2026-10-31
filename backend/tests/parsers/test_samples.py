"""Эталоны на реальных извещениях ЕИС из data/samples.

Значения сверены вручную с XML. Локально образцы лежат в корне репозитория, в контейнере —
в /repo/data/samples; если их нет, тесты пропускаются.
"""

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.normalize import inn_is_valid
from app.parsers.registry import parse_file
from app.schemas.procurement import ProcurementData

_CANDIDATES = [Path(__file__).parents[3] / "data" / "samples", Path("/repo/data/samples")]
SAMPLES = next((p for p in _CANDIDATES if p.is_dir()), None)
pytestmark = pytest.mark.skipif(SAMPLES is None, reason="нет data/samples")


def _parse(reg: str) -> list[ProcurementData]:
    assert SAMPLES is not None
    return parse_file((SAMPLES / f"{reg}.xml").read_bytes(), f"{reg}.xml")


def _all_samples() -> list[str]:
    return sorted(p.name for p in SAMPLES.glob("*.xml")) if SAMPLES else []


# Чего нет в самом извещении (сверено с карточкой на сайте ЕИС)
_ABSENT = {
    "0319200064426000189.xml": {"application_deadline"},  # электронный магазин
    "32616510892.xml": {"nmck"},  # запрос цен для формирования НМЦК: цена 0,00 ₽
}


@pytest.mark.parametrize("name", _all_samples())
def test_every_sample_parses(name: str) -> None:
    """Полнота по ключевым полям ТЗ: НМЦК, способ, регион, сроки, заказчик."""
    assert SAMPLES is not None
    content = (SAMPLES / name).read_bytes()
    lots = parse_file(content, name)
    assert lots
    absent = _ABSENT.get(name, set())
    # До 2016 г. ИКЗ не было: если закупку размещал уполномоченный орган (напр.
    # 0194200000514002239), ИНН заказчика в извещении нет вовсе
    no_ikz = b"customerCode>" not in content
    by_agency = re.search(rb"responsibleRole>(?!CU)", content) is not None
    inn_expected = not (no_ikz and by_agency)
    for p in lots:
        assert p.reg_number.split("-")[0] == name.removesuffix(".xml")
        assert p.nmck > 0 or "nmck" in absent
        assert p.method is not None
        assert p.region is not None
        assert p.application_deadline is not None or "application_deadline" in absent
        if inn_expected:
            assert p.customer_inn is not None and inn_is_valid(p.customer_inn)
        assert p.parsed_by != "universal" or p.law == "615"


def test_44_ef2020_customer_places_itself() -> None:
    [p] = _parse("0338200009826000713")
    assert p.parsed_by == "adapter:eis44"
    assert p.law == "44"
    assert p.subject == "Поставка реагентов на анализатор Minividas"
    assert p.nmck == Decimal("774859.70")
    assert p.method == "auction"
    assert p.customer_inn == "4101039153"
    assert p.region == "Камчатский край"
    assert p.application_deadline == datetime(2026, 10, 29, 8, 9, tzinfo=UTC)
    assert p.delivery_term_text == "по 31.12.2027"
    assert p.okpd2_codes == ["21.20.23.110", "20.59.52.195"]
    assert len(p.items) == 2
    assert p.bid_security is None
    assert p.contract_security == Decimal("77485.97")
    assert p.contract_security_pct == Decimal("10.00")


def test_44_joint_purchase_by_authorized_body() -> None:
    """Совместная закупка через уполномоченный орган: ИНН — из ИКЗ первого заказчика,
    обеспечение — процент от общей НМЦК, а не доля одного заказчика."""
    [p] = _parse("0820500000826005020")
    assert p.nmck == Decimal("13403272.74")
    assert p.customer_inn == "2536096273"
    assert p.customer_name and "ВЛАДИВОСТОКСКАЯ (КОРРЕКЦИОННАЯ)" in p.customer_name
    assert p.bid_security == Decimal("134032.73") and p.bid_security_pct == Decimal("1.0")
    assert p.contract_security == Decimal("1340327.27")
    assert p.restrictions == ["prefs_uis"]
    assert p.delivery_term_text == "с 01.01.2027 по 30.11.2027"


def test_44_drugs() -> None:
    [p] = _parse("0820500000826005437")
    assert p.customer_inn == "2537021785"
    assert [i.okpd2 for i in p.items] == ["21.20.10.132"]
    assert p.items[0].name.startswith("ТРАНЕКСАМОВАЯ КИСЛОТА")
    assert p.restrictions == ["smp_only"]  # «ч. 3 ст. 30 Закона № 44-ФЗ»


def test_44_contest_with_securities() -> None:
    [p] = _parse("0102200001626002273")
    assert p.method == "contest"
    assert p.customer_inn == "0320001892"
    assert p.region == "Республика Бурятия"
    assert p.application_deadline == datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    assert p.bid_security == Decimal("169434.82")
    assert p.contract_security == Decimal("1694348.21")
    assert p.delivery_days == 84


def test_44_old_fcs_format() -> None:
    [p] = _parse("0820500000821002973")
    assert p.parsed_by == "adapter:eis44"
    assert p.nmck == Decimal("888624")
    assert p.customer_inn == "2504001670"
    assert p.delivery_term_text == "с момента заключения контракта и до 31.08.2021г."
    assert p.delivery_days == 112
    assert p.okpd2_codes == ["43.21.10.140"]


def test_44_electronic_store() -> None:
    """Электронный магазин (ч. 12 ст. 93): нет purchaseObjectInfo — предмет из позиции;
    срока подачи заявок в извещении нет."""
    [p] = _parse("0319200064426000189")
    assert p.parsed_by == "adapter:eis44"
    assert p.subject == "Шина пневматическая для легкового автомобиля"
    assert p.nmck == Decimal("146535.62")
    assert p.method == "other"
    assert p.customer_inn == "2450010010"
    assert p.region == "Красноярский край"
    assert p.application_deadline is None
    assert p.delivery_term_text == "по 30.12.2026"
    assert p.okpd2_codes == ["22.11.11.000"]
    assert p.contract_security == Decimal("7326.78")


def test_223_multilot() -> None:
    lots = _parse("32211747866")
    assert [p.reg_number for p in lots] == [f"32211747866-{i}" for i in range(1, 5)]
    assert [p.nmck for p in lots] == [
        Decimal("26669.5"),
        Decimal("1259180"),
        Decimal("428010"),
        Decimal("1737999.2"),
    ]
    assert lots[1].subject == "Кабель силовой медный КГтп 4х50- 0,660"
    assert {p.customer_inn for p in lots} == {"5403173213"}
    assert {p.region for p in lots} == {"Новосибирская область"}


def test_223_smp_with_contract_security_text() -> None:
    [p] = _parse("32616529772")
    assert p.parsed_by == "adapter:eis223"
    assert p.method == "auction"
    assert p.restrictions == ["smp_only"]
    assert p.region == "Приморский край"  # lotData/deliveryPlace/region
    assert p.application_deadline == datetime(2026, 11, 8, 23, 0, tzinfo=UTC)  # 09:00 МСК+7
    assert p.contract_security_pct == Decimal("5")  # «5% от начальной (максимальной) цены»
    assert p.contract_security == Decimal("116666.50")


def test_223_max_contract_price() -> None:
    """Новая схема 223-ФЗ: НМЦК лота в maxContractPrice; адрес поставки в файле —
    мусор, регион берётся по адресу заказчика."""
    [p] = _parse("32616481510")
    assert p.parsed_by == "adapter:eis223"
    assert p.nmck == Decimal("9000000")
    assert p.method == "proposals"
    assert p.customer_inn == "1435028701"
    assert p.region == "Республика Саха (Якутия)"
    assert p.application_deadline == datetime(2026, 10, 29, 9, 0, tzinfo=UTC)  # 18:00 МСК+6


def test_223_centralized_lot_price_from_customer() -> None:
    """Централизованная закупка: у лота initialSum = 0 (на сайте ЕИС «0,00 ₽»), цена — у
    заказчика в jointLotData/lotCustomers."""
    [p] = _parse("32616514797")
    assert p.parsed_by == "adapter:eis223"
    assert p.nmck == Decimal("273049.92")
    assert p.subject.startswith("Оказание услуг аудита бухгалтерской (финансовой) отчетности")
    assert p.method == "other" and p.method_raw == "Тендер"
    assert p.customer_inn == "9701142641"
    assert p.region == "Москва"
    assert p.okpd2_codes == ["69.20.10.000"]
    assert p.application_deadline == datetime(2026, 11, 5, 13, 0, tzinfo=UTC)  # 16:00 МСК


def test_223_price_request_without_nmck() -> None:
    """Запрос цен для формирования НМЦК: начальной цены нет, в документе 0 — это значение."""
    [p] = _parse("32616510892")
    assert p.parsed_by == "adapter:eis223"
    assert p.nmck == 0
    assert p.subject == "Страхование имущества (КАС)"
    assert p.method == "proposals"
    assert p.customer_inn == "2466189073"
    assert p.region == "Красноярский край"
    # время в 223-ФЗ — местное время заказчика: на сайте ЕИС «02.11.2026 10:00 (МСК+4)»
    assert p.application_deadline == datetime(2026, 11, 2, 3, 0, tzinfo=UTC)
    assert p.published_at == datetime(2026, 10, 27, 7, 30, 49, tzinfo=UTC)


def test_615_universal() -> None:
    [p] = _parse("203950000012401084")
    assert p.parsed_by == "universal"
    assert p.law == "615"
    assert p.nmck == Decimal("242699.25")
    assert p.method == "auction"
    assert p.customer_inn == "4205997094"
    assert p.region == "Кемеровская область"
    assert p.application_deadline == datetime(2024, 10, 25, 10, 0, tzinfo=UTC)
    assert p.bid_security == Decimal("2426.99")
    assert p.delivery_days == 318  # «не позднее 31.08.2025»
