"""PDF-этикетка товара со штрихкодом.

Ozon не отдаёт этикетку товара через Seller API (есть только создание
штрихкода `/v1/barcode/generate`), поэтому стикер печатаем сами — по образцу
этикетки из личного кабинета Ozon: сверху цифры штрихкода, под ними полоса
штрихкода во всю ширину, ниже артикул продавца и название товара.
Размер — 58×40 мм, стандартная термоэтикетка.
"""

from __future__ import annotations

import glob
import os
from io import BytesIO

from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.colors import black
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

LABEL_WIDTH = 58 * mm
LABEL_HEIGHT = 40 * mm
LABEL_PADDING = 2.5 * mm

# Раскладка повторяет этикетку из личного кабинета Ozon: сверху цифры штрихкода,
# под ними полоса штрихкода во всю ширину, ниже артикул и название товара.
DIGITS_FONT_SIZE = 9.0
DIGITS_MIN_FONT_SIZE = 4.5
DIGITS_GAP = 0.9 * mm

BARCODE_BAR_HEIGHT = 17 * mm
# Толщина штриха (pt): стартовая и пределы, между ними подгоняем под ширину стикера.
BARCODE_BAR_WIDTH = 0.5
BARCODE_MAX_BAR_WIDTH = 2.5
BARCODE_MIN_BAR_WIDTH = 0.5
BARCODE_MAX_CODE128_LEN = 48

TEXT_FONT_SIZE = 8.0
TEXT_LEADING = 3.5 * mm
TEXT_GAP = 1.3 * mm
TEXT_MAX_LINES = 4

# Доля кегля от верхнего края строки до базовой линии (для DejaVu/Helvetica).
_ASCENT_RATIO = 0.72

# Кириллицу умеют DejaVu, Noto Sans и Liberation Sans. Если ни одного шрифта в
# системе нет, остаётся Helvetica — она печатает только латиницу.
_FONT_FAMILIES = (
    ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
    ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
)
_FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/noto",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
)
_FONT_RECURSIVE_ROOT = "/usr/share/fonts"

_fonts: tuple[str, str, bool] | None = None


def _find_font_file(filename: str) -> str | None:
    """Ищет файл шрифта в стандартных каталогах, при необходимости рекурсивно."""
    for directory in _FONT_DIRS:
        path = os.path.join(directory, filename)
        if os.path.exists(path):
            return path
    matches = glob.glob(os.path.join(_FONT_RECURSIVE_ROOT, "**", filename), recursive=True)
    return matches[0] if matches else None


def _register_font(font_name: str, filename: str) -> str | None:
    """Регистрирует TTF-шрифт из системного каталога, если он есть."""
    path = _find_font_file(filename)
    if not path:
        return None
    try:
        pdfmetrics.registerFont(TTFont(font_name, path))
    except Exception:  # noqa: BLE001 — битый шрифт не должен ломать печать
        return None
    return font_name


def _label_fonts() -> tuple[str, str, bool]:
    """Шрифты этикетки: (обычный, жирный, поддерживается ли кириллица)."""
    global _fonts
    if _fonts is not None:
        return _fonts

    for regular_file, bold_file in _FONT_FAMILIES:
        regular = _register_font("OzonLabelRegular", regular_file)
        if not regular:
            continue
        bold = _register_font("OzonLabelBold", bold_file) or regular
        _fonts = (regular, bold, True)
        return _fonts

    _fonts = ("Helvetica", "Helvetica-Bold", False)
    return _fonts


def _printable_text(text: str, cyrillic_ok: bool) -> str:
    """Убирает символы, которые не напечатает выбранный шрифт."""
    value = str(text or "").strip()
    if cyrillic_ok:
        return value
    return value.encode("ascii", "ignore").decode("ascii").strip()


def _fit_line(text: str, font: str, size: float, max_width: float) -> str:
    """Обрезает строку по ширине с многоточием."""
    if pdfmetrics.stringWidth(text, font, size) <= max_width:
        return text
    truncated = text
    while truncated and pdfmetrics.stringWidth(truncated + "…", font, size) > max_width:
        truncated = truncated[:-1]
    return f"{truncated.rstrip()}…" if truncated else ""


def _fit_font_size(
    text: str,
    font: str,
    size: float,
    min_size: float,
    max_width: float,
) -> float:
    """Уменьшает кегль строки, пока она не влезет в ширину стикера."""
    current = size
    while current > min_size and pdfmetrics.stringWidth(text, font, current) > max_width:
        current = max(min_size, current - 0.5)
    return current


def _wrap_text(
    text: str,
    font: str,
    size: float,
    max_width: float,
    max_lines: int,
) -> list[str]:
    """Разбивает текст на строки по ширине, лишнее сворачивает в многоточие."""
    words = str(text or "").split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = f"{lines[-1]} …"

    return [_fit_line(line, font, size, max_width) for line in lines]


def _ean_check_digit(body: str) -> str:
    """Контрольная цифра EAN-13/EAN-8/UPC-A для первых цифр кода."""
    total = 0
    for index, char in enumerate(reversed(body)):
        total += int(char) * (3 if index % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def _barcode_kind(value: str) -> str | None:
    """Тип штрихкода для печати или None, если значение напечатать нельзя."""
    if not value or not value.isascii() or not value.isprintable():
        return None

    if value.isdigit():
        # Длина кода → тип и сколько цифр отводится под тело без контрольной.
        kinds = {13: ("EAN13", 12), 12: ("UPCA", 11), 8: ("EAN8", 7)}
        kind = kinds.get(len(value))
        if kind and _ean_check_digit(value[: kind[1]]) == value[kind[1]]:
            return kind[0]

    # Всё остальное (например, внутренние ШК Ozon вида OZN1234567) — Code128.
    if len(value) <= BARCODE_MAX_CODE128_LEN:
        return "Code128"
    return None


def _make_barcode(kind: str, value: str, bar_width: float):
    try:
        return createBarcodeDrawing(
            kind,
            value=value,
            barWidth=bar_width,
            barHeight=BARCODE_BAR_HEIGHT,
            # Цифры печатаем сами над штрихкодом, поля стикера задаём тоже сами.
            humanReadable=False,
            quiet=False,
        )
    except Exception:  # noqa: BLE001 — reportlab бросает разные ошибки валидации
        return None


def _barcode_drawing(value: str, max_width: float):
    """Штрихкод на всю ширину стикера."""
    kind = _barcode_kind(value)
    if not kind:
        return None

    probe = _make_barcode(kind, value, BARCODE_BAR_WIDTH)
    if probe is None or probe.width <= 0:
        return None

    # Ширина штрихкода линейна по barWidth: сразу считаем нужную толщину штриха.
    modules = probe.width / BARCODE_BAR_WIDTH
    if modules <= 0:
        return probe
    bar_width = min(BARCODE_MAX_BAR_WIDTH, max(BARCODE_MIN_BAR_WIDTH, max_width / modules))
    drawing = _make_barcode(kind, value, bar_width)
    if drawing is None or drawing.width <= 0:
        return probe
    if drawing.width > max_width:
        finer = _make_barcode(kind, value, bar_width * max_width / drawing.width)
        if finer is not None and 0 < finer.width <= max_width:
            drawing = finer
    return drawing


def _render_label(canvas: Canvas, name: str, offer_id: str, barcode: str) -> None:
    """Раскладывает цифры, штрихкод, артикул и название как на этикетке Ozon."""
    regular, _bold, cyrillic_ok = _label_fonts()
    left = LABEL_PADDING
    width = LABEL_WIDTH - 2 * LABEL_PADDING
    top = LABEL_HEIGHT - LABEL_PADDING

    # 1. Цифры штрихкода сверху — так их печатает Ozon в личном кабинете.
    barcode_text = _printable_text(barcode, True)
    digits_size = _fit_font_size(
        barcode_text, regular, DIGITS_FONT_SIZE, DIGITS_MIN_FONT_SIZE, width
    )
    digits_text = _fit_line(barcode_text, regular, digits_size, width)
    digits_baseline = top - digits_size * _ASCENT_RATIO
    if digits_text:
        canvas.setFont(regular, digits_size)
        canvas.setFillColor(black)
        canvas.drawString(left, digits_baseline, digits_text)

    # 2. Полоса штрихкода во всю ширину стикера, сразу под цифрами.
    bars_bottom = digits_baseline - DIGITS_GAP - BARCODE_BAR_HEIGHT
    drawing = _barcode_drawing(barcode_text, width)
    if drawing is not None:
        drawing.drawOn(canvas, left + max(0.0, (width - drawing.width) / 2), bars_bottom)

    # 3. Артикул и название товара под штрихкодом — одним кеглем, без выделений.
    baseline = bars_bottom - TEXT_GAP - TEXT_FONT_SIZE * _ASCENT_RATIO
    canvas.setFont(regular, TEXT_FONT_SIZE)
    canvas.setFillColor(black)

    offer_text = _fit_line(_printable_text(offer_id, cyrillic_ok), regular, TEXT_FONT_SIZE, width)
    if offer_text:
        canvas.drawString(left, baseline, offer_text)
        baseline -= TEXT_LEADING

    max_lines = 1 + int(max(0.0, baseline - LABEL_PADDING) // TEXT_LEADING)
    max_lines = max(1, min(max_lines, TEXT_MAX_LINES))
    name_lines = _wrap_text(
        _printable_text(name, cyrillic_ok),
        regular,
        TEXT_FONT_SIZE,
        width,
        max_lines,
    )
    for line in name_lines:
        canvas.drawString(left, baseline, line)
        baseline -= TEXT_LEADING


def _label_filename(product) -> str:
    """Имя файла: артикул, если он латиницей, иначе ID товара в Ozon."""
    offer = str(product.offer_id or "").strip()
    if offer and offer.isascii():
        slug = offer
    else:
        slug = str(product.ozon_product_id or product.id)
    return f"label-{slug}.pdf"


def build_product_label(product) -> dict:
    """PDF-этикетка товара для скачивания.

    Возвращает {"ok": True, "content": bytes, "filename": str} либо
    {"ok": False, "error": str} с текстом для пользователя.
    """
    barcode = str(product.barcode or "").strip()
    if not barcode:
        return {
            "ok": False,
            "error": "У товара нет штрихкода. Синхронизируйте товары из Ozon.",
        }
    if _barcode_kind(barcode) is None:
        return {
            "ok": False,
            "error": "Штрихкод товара нельзя напечатать: Ozon вернул неподдерживаемое значение.",
        }

    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(LABEL_WIDTH, LABEL_HEIGHT))
    canvas.setTitle(f"Этикетка {product.offer_id or product.ozon_product_id or product.id}")
    _render_label(canvas, str(product.name or ""), str(product.offer_id or ""), barcode)
    canvas.showPage()
    canvas.save()

    content = buffer.getvalue()
    if not content:
        return {"ok": False, "error": "Не удалось сформировать этикетку товара."}

    return {
        "ok": True,
        "content": content,
        "filename": _label_filename(product),
    }

