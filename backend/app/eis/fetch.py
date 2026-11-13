"""Скачивание XML печатной формы извещения из ЕИС по реестровому номеру (задача B).

- 11 цифр — 223-ФЗ, два запроса: карточка закупки (в её HTML лежит GUID извещения),
  затем XML печатной формы по GUID;
- 18 цифр (ПП РФ 615) и 19 цифр (44-ФЗ) — один запрос к общей печатной форме.

zakupki.gov.ru подписан сертификатом Минцифры, которого нет в certifi: он лежит рядом
с модулем (`russian_trusted_ca.pem`, корневой и промежуточный) и добавляется к доверенным.
Капчу и блокировки не обходим: всё, что не XML, — EIS_UNAVAILABLE.
"""

import logging
import re
import ssl
import threading
import time
from functools import lru_cache
from pathlib import Path

import certifi
import httpx

from app.eis import EisError
from app.schemas.common import ErrorCode

log = logging.getLogger(__name__)

BASE_URL = "https://zakupki.gov.ru/epz/order/notice"
PRINT_FORM_URL = f"{BASE_URL}/printForm/viewXml.html"
CARD_223_URL = f"{BASE_URL}/notice223/common-info.html"
PRINT_FORM_223_URL = f"{BASE_URL}/notice223/printForm/viewXml.html"

CA_PATH = Path(__file__).with_name("russian_trusted_ca.pem")
# Браузерный заголовок (решение тимлида, 13.11.2026): на запросы с заголовком сервиса ЕИС
# отвечает пустым 404, как и зарубежным адресам
USER_AGENT = "Mozilla/5.0"
TIMEOUT = httpx.Timeout(30.0)
PAUSE_SECONDS = 1.0  # между любыми двумя запросами к ЕИС
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0  # перед повтором: 2 с, 4 с, ...
# ЕИС не ответила — следующие номера пакета не ждут повторов, а сразу получают EIS_UNAVAILABLE
# (и образец из data/samples, если он есть): список из 200 номеров не висит полчаса
COOLDOWN_SECONDS = 60.0

_GUID_RE = re.compile(r"purchaseNoticeGuid=([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
_BOM = b"\xef\xbb\xbf"
NOT_FOUND_MARK = "Страница не найдена"

_pause_lock = threading.Lock()
_last_request = 0.0
_down_until = 0.0


@lru_cache
def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.load_verify_locations(cafile=str(CA_PATH))
    return ctx


def _client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """transport подменяется в тестах."""
    return httpx.Client(
        transport=transport,
        verify=_ssl_context(),
        timeout=TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/xml, text/html;q=0.9"},
    )


def _wait_turn() -> None:
    """Не чаще одного запроса в PAUSE_SECONDS на процесс воркера."""
    global _last_request
    with _pause_lock:
        delay = _last_request + PAUSE_SECONDS - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        _last_request = time.monotonic()


def _unavailable(reason: str) -> EisError:
    return EisError(ErrorCode.EIS_UNAVAILABLE, f"ЕИС недоступна: {reason}")


def _get(client: httpx.Client, url: str, params: dict[str, str]) -> httpx.Response:
    """GET с паузой и повторами. Повторяются таймаут, обрыв связи, 5xx и 404 без страницы ЕИС.

    «Не найдено» — только 404 со страницей ЕИС «Страница не найдена». С зарубежного адреса
    (VPN, зарубежный хостинг) ЕИС отвечает пустым 404 от веб-сервера на любой номер, даже
    существующий (отдаются лишь страницы из кэша), — это EIS_UNAVAILABLE, иначе вместо
    сохранённого образца пользователь увидел бы «закупка не найдена».
    Прочие ответы (403, 429, переадресация) — блокировка, повтором её не продавливаем."""
    reason = "нет ответа"
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(RETRY_DELAY_SECONDS * 2 ** (attempt - 1))
        _wait_turn()
        try:
            r = client.get(url, params=params)
        except httpx.TimeoutException:
            reason = "нет ответа за отведённое время"
            continue
        except httpx.HTTPError as e:
            reason = f"ошибка соединения ({type(e).__name__})"
            continue
        if r.status_code == 404:
            if NOT_FOUND_MARK in r.text:
                raise EisError(ErrorCode.EIS_NOT_FOUND, "Закупка с таким номером не найдена в ЕИС")
            reason = "ответ 404 без страницы ЕИС (так она отвечает зарубежным адресам)"
            continue
        if r.status_code >= 500:
            reason = f"ответ {r.status_code}"
            continue
        if r.status_code != 200:
            raise _unavailable(f"ответ {r.status_code}")
        return r
    raise _unavailable(reason)


def _xml(r: httpx.Response) -> bytes:
    body = r.content
    head = body.removeprefix(_BOM).lstrip()[:5]
    if head != b"<?xml" or "html" in r.headers.get("content-type", "").lower():
        raise _unavailable("вместо XML пришла веб-страница (возможно, проверка «я не робот»)")
    return body


def fetch_notice(reg_number: str) -> bytes:
    """XML печатной формы извещения. Ошибки — только EisError."""
    global _down_until
    try:
        if time.monotonic() < _down_until:
            raise _unavailable("недавно не отвечала, запросы приостановлены")
        return _fetch(reg_number)
    except EisError as e:
        if e.code == ErrorCode.EIS_UNAVAILABLE and time.monotonic() >= _down_until:
            _down_until = time.monotonic() + COOLDOWN_SECONDS
        log.info("ЕИС, номер %s: %s — %s", reg_number, e.code.value, e.message)
        raise
    except Exception as e:  # контракт: наружу только EisError
        log.warning("ЕИС, номер %s: неожиданная ошибка %s", reg_number, type(e).__name__)
        raise _unavailable(type(e).__name__) from e


def _fetch(reg_number: str) -> bytes:
    with _client() as client:
        if len(reg_number) != 11:
            return _xml(_get(client, PRINT_FORM_URL, {"regNumber": reg_number}))
        card = _get(client, CARD_223_URL, {"regNumber": reg_number})
        found = _GUID_RE.search(card.text)
        if found is None:
            # Несуществующий номер ЕИС отдаёт с кодом 404; страница без ссылки на
            # печатную форму — это капча или изменившаяся вёрстка, а не «не найдено»
            raise _unavailable("в карточке закупки нет ссылки на печатную форму")
        params = {"purchaseNoticeGuid": found.group(1), "purchaseNoticeNumber": reg_number}
        return _xml(_get(client, PRINT_FORM_223_URL, params))
