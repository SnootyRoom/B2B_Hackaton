"""Скачивание извещения из ЕИС: сеть подменена httpx.MockTransport, паузы не выполняются."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from app.eis import EisError, fetch
from app.parsers.registry import parse_xml
from app.schemas.common import ErrorCode

FIXTURES = Path(__file__).parents[1] / "parsers" / "fixtures"
XML_44 = (FIXTURES / "notice44_ef2020.xml").read_bytes()
XML_223 = (FIXTURES / "notice223_multilot.xml").read_bytes()
N44 = "0365200000026000123"
N223 = "32616481510"
N615 = "203950000012401084"
GUID = "38162440-518e-4c65-bc1e-5c44525742b8"
CARD_223 = (
    "<html><body><a href='/epz/order/notice/notice223/printForm/view.html"
    f"?purchaseNoticeGuid={GUID}&purchaseNoticeNumber={N223}'>Печатная форма</a></body></html>"
)
CAPTCHA = "<html><body>Подтвердите, что вы не робот</body></html>"
BARE_404 = "<html><head><title>404 Not Found</title></head><body>nginx</body></html>"
NOT_FOUND = "<html><head><title> Страница не найдена </title></head></html>"

Handler = Callable[[httpx.Request], httpx.Response]


def _xml(content: bytes) -> httpx.Response:
    return httpx.Response(200, content=content, headers={"content-type": "text/xml;charset=UTF-8"})


def _html(text: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=text, headers={"content-type": "text/html;charset=UTF-8"})


class Eis:
    """Поддельная ЕИС: запоминает запросы и паузы."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, handler: Handler) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

        def handle(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        real_client = fetch._client
        monkeypatch.setattr(fetch, "_client", lambda: real_client(httpx.MockTransport(handle)))
        monkeypatch.setattr("app.eis.fetch.time.sleep", self.sleeps.append)
        monkeypatch.setattr(fetch, "_last_request", 0.0)
        monkeypatch.setattr(fetch, "_down_until", 0.0)


def _fails(number: str) -> EisError:
    with pytest.raises(EisError) as e:
        fetch.fetch_notice(number)
    return e.value


@pytest.mark.parametrize("number", [N44, N615])
def test_44_one_request(monkeypatch: pytest.MonkeyPatch, number: str) -> None:
    eis = Eis(monkeypatch, lambda r: _xml(XML_44))
    assert fetch.fetch_notice(number) == XML_44
    (request,) = eis.requests
    assert request.url.path == "/epz/order/notice/printForm/viewXml.html"
    assert request.url.params["regNumber"] == number
    assert request.headers["user-agent"] == fetch.USER_AGENT


def test_223_multilot_two_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return _html(CARD_223) if r.url.path.endswith("common-info.html") else _xml(XML_223)

    eis = Eis(monkeypatch, handler)
    content = fetch.fetch_notice(N223)
    card, form = eis.requests
    assert card.url.path == "/epz/order/notice/notice223/common-info.html"
    assert card.url.params["regNumber"] == N223
    assert form.url.path == "/epz/order/notice/notice223/printForm/viewXml.html"
    assert dict(form.url.params) == {"purchaseNoticeGuid": GUID, "purchaseNoticeNumber": N223}
    # тот же путь обработки, что у файла: все лоты
    assert [p.reg_number for p in parse_xml(content)] == [f"{N223}-1", f"{N223}-2"]


def test_pause_between_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    eis = Eis(monkeypatch, lambda r: _xml(XML_44))
    fetch.fetch_notice(N44)
    fetch.fetch_notice(N44)
    assert len(eis.sleeps) == 1
    assert 0 < eis.sleeps[0] <= fetch.PAUSE_SECONDS


@pytest.mark.parametrize("number", [N44, N223])
def test_eis_not_found_page(monkeypatch: pytest.MonkeyPatch, number: str) -> None:
    eis = Eis(monkeypatch, lambda r: _html(NOT_FOUND, 404))
    assert _fails(number).code == ErrorCode.EIS_NOT_FOUND
    assert len(eis.requests) == 1  # ответ самой ЕИС — без повторов


def test_bare_404_is_unavailable_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Зарубежный адрес (VPN): 404 веб-сервера на любой номер — это не «не найдено»."""
    eis = Eis(monkeypatch, lambda r: _html(BARE_404, 404))
    assert _fails(N44).code == ErrorCode.EIS_UNAVAILABLE
    assert len(eis.requests) == fetch.ATTEMPTS


def test_recovers_after_bare_404(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([_html(BARE_404, 404), _html(CARD_223), _html(BARE_404, 404), _xml(XML_223)])
    eis = Eis(monkeypatch, lambda r: next(responses))
    assert fetch.fetch_notice(N223) == XML_223
    assert len(eis.requests) == 4


@pytest.mark.parametrize(
    "response",
    [
        _html(CAPTCHA),
        # страница, прикинувшаяся XML по заголовку, и XHTML с text/html
        _xml(b"<!DOCTYPE html><html><body>captcha</body></html>"),
        _html('<?xml version="1.0"?><html xmlns="http://www.w3.org/1999/xhtml"/>'),
    ],
)
def test_html_instead_of_xml_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, response: httpx.Response
) -> None:
    eis = Eis(monkeypatch, lambda r: response)
    assert _fails(N44).code == ErrorCode.EIS_UNAVAILABLE
    assert len(eis.requests) == 1


def test_223_card_without_guid_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    eis = Eis(monkeypatch, lambda r: _html(CAPTCHA))
    assert _fails(N223).code == ErrorCode.EIS_UNAVAILABLE
    assert len(eis.requests) == 1


@pytest.mark.parametrize("status", [403, 429, 302])
def test_block_is_unavailable_without_retry(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    eis = Eis(monkeypatch, lambda r: _html("blocked", status))
    assert _fails(N44).code == ErrorCode.EIS_UNAVAILABLE
    assert len(eis.requests) == 1


def test_timeout_retries_with_growing_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=r)

    eis = Eis(monkeypatch, handler)
    assert _fails(N44).code == ErrorCode.EIS_UNAVAILABLE
    assert len(eis.requests) == fetch.ATTEMPTS
    assert [s for s in eis.sleeps if s >= fetch.RETRY_DELAY_SECONDS] == [2.0, 4.0]


def test_recovers_after_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([_html("bad gateway", 502), _xml(XML_44)])
    eis = Eis(monkeypatch, lambda r: next(responses))
    assert fetch.fetch_notice(N44) == XML_44
    assert len(eis.requests) == 2


def test_connection_error_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("certificate verify failed", request=r)

    Eis(monkeypatch, handler)
    assert _fails(N44).code == ErrorCode.EIS_UNAVAILABLE


def test_cooldown_after_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """ЕИС не ответила — следующие номера не ждут повторов; после паузы запросы идут снова."""
    eis = Eis(monkeypatch, lambda r: _html("bad gateway", 503))
    assert _fails(N44).code == ErrorCode.EIS_UNAVAILABLE
    assert _fails(N223).code == ErrorCode.EIS_UNAVAILABLE
    assert len(eis.requests) == fetch.ATTEMPTS  # второй номер в ЕИС не ходил
    monkeypatch.setattr(fetch, "_down_until", 0.0)
    _fails(N223)
    assert len(eis.requests) == 2 * fetch.ATTEMPTS


def test_not_found_does_not_start_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = iter([_html(NOT_FOUND, 404), _xml(XML_44)])
    Eis(monkeypatch, lambda r: next(responses))
    assert _fails(N44).code == ErrorCode.EIS_NOT_FOUND
    assert fetch.fetch_notice(N44) == XML_44


def test_ca_bundle_loads() -> None:
    fetch._ssl_context.cache_clear()
    assert fetch.CA_PATH.is_file()
    names = str(fetch._ssl_context().get_ca_certs())
    assert "Russian Trusted Root CA" in names
    assert "Russian Trusted Sub CA" in names
