"""Чтение XML: только локальные имена тегов в нижнем регистре, namespaces отбрасываются.

После `load_xml` пути пишутся без префиксов: `commoninfo/purchasenumber`.
"""

from lxml import etree

from app.parsers.errors import unsupported_format

_PARSER = etree.XMLParser(
    resolve_entities=False, no_network=True, remove_comments=True, remove_pis=True
)

Element = etree._Element

# Обёртки, внутри которых лежит сам документ (печатная форма, выгрузка)
_WRAPPERS = {"export", "body", "item", "document", "data"}


def load_xml(content: bytes) -> Element:
    try:
        root = etree.fromstring(content, _PARSER)
    except (etree.XMLSyntaxError, ValueError) as e:
        raise unsupported_format() from e
    if root is None:
        raise unsupported_format()
    for el in root.iter():
        if isinstance(el.tag, str):
            el.tag = etree.QName(el).localname.lower()
    etree.cleanup_namespaces(root)
    return root


def document_root(root: Element) -> Element:
    """Снимает обёртки вида <export><epNotificationEF2020>…: возвращает сам документ."""
    node = root
    while node.tag in _WRAPPERS:
        children = [c for c in node if isinstance(c.tag, str)]
        if len(children) != 1:
            break
        node = children[0]
    return node


def text(el: Element) -> str | None:
    value = "".join(t for t in el.itertext() if isinstance(t, str)).strip()
    return value or None


def select(ctx: Element, path: str) -> list[Element]:
    """XPath от ctx; пути в спецификациях выбирают только элементы."""
    found = ctx.xpath(path)
    return [el for el in found if isinstance(el, etree._Element)] if isinstance(found, list) else []


def first(ctx: Element, paths: tuple[str, ...]) -> str | None:
    """Первое непустое значение по списку путей."""
    for path in paths:
        for el in select(ctx, path):
            if value := text(el):
                return value
    return None


def all_texts(ctx: Element, paths: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    for path in paths:
        for el in select(ctx, path):
            value = text(el)
            if value and value not in result:
                result.append(value)
    return result


def nodes(ctx: Element, paths: tuple[str, ...]) -> list[Element]:
    """Узлы по первому пути, который что-то нашёл."""
    for path in paths:
        if found := select(ctx, path):
            return found
    return []
