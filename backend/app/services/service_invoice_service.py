"""Read a workshop invoice into a draft service visit (never writes one).

The fuel form reads a fuel slip; this reads the paper a workshop hands over:
a service or tax invoice, a job card, a quote. Two paths, like the document
reader it builds on:

* A PDF with a text layer has its text laid out row by row (PyMuPDF words
  grouped by line, so a table row stays one line with its columns in order)
  and sent to the text model (``llm_model``).
* A photo or scanned PDF is OCR'd (Tesseract keeps a table row on one line)
  and the text goes to the same text model. Measured on a 23-line tax
  invoice: OCR + qwen2.5:7b had the workshop, date, odometer, tax and total
  right and 22 lines exact; gemma3:4b reading the images took the customer
  for the workshop and misread the totals.
* Only when OCR finds no text does the file go to the vision model through
  ``document_reader_service.read_document``.

Both need AI document reading (``llm_document_reading_enabled``) and, for a
model outside the household's network, the person's consent: an invoice
carries a name, an address and a phone number.

The model is asked for values as printed. What a small model gets wrong is
which column it copies, so the draft never trusts one column: the lines are
checked against the invoice's own totals (`reconcile`), which says whether
the amounts are before or after tax, and the tax is split back out when the
lines carry it. A draft whose lines don't add up still comes back, with a
warning, for the person to fix before saving.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.vendor import Vendor
from app.services import document_reader_service, llm_client
from app.services.document_images import has_text_layer, is_pdf, to_images
from app.services.document_prompts import prompt_for
from app.utils.logging_utils import sanitize_for_log

logger = logging.getLogger(__name__)

KIND = "service_invoice"
#: Enough for a three-page invoice; the rest is terms and banking details.
MAX_TEXT_CHARS = 14_000
#: Less OCR text than this is a photo OCR could not read: try the vision model.
MIN_OCR_CHARS = 150
MAX_PAGES = 4
MAX_LINES = 80
DESCRIPTION_MAX = 200
CENT = Decimal("0.01")

_LINE_KINDS = {"labour", "part", "fee", "other"}
_KIND_ALIASES = {
    "labor": "labour",
    "parts": "part",
    "material": "part",
    "materials": "part",
    "sublet": "other",
}


# --- Text layer --------------------------------------------------------------


def layout_text(pdf_bytes: bytes, *, max_pages: int = MAX_PAGES) -> str:
    """The PDF's words, one printed row per line, columns separated by `` | ``.

    PyMuPDF's plain text puts every table cell on its own line, column by
    column, which leaves a model to guess which price belongs to which part.
    Grouping words by their vertical centre keeps a row together.
    """
    import pymupdf

    out: list[str] = []
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page_number, page in enumerate(page for page in doc):
            if page_number >= max_pages:
                break
            rows: list[tuple[float, list[tuple[Any, ...]]]] = []
            found = page.get_text("words")
            # "words" is a list of (x0, y0, x1, y1, text, ...); the stub says str | list | dict.
            if not isinstance(found, list):
                continue
            entries = cast(list[tuple[Any, ...]], found)
            words = sorted(entries, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
            for word in words:
                middle = (word[1] + word[3]) / 2
                height = word[3] - word[1]
                if rows and abs(rows[-1][0] - middle) <= height * 0.45:
                    rows[-1][1].append(word)
                else:
                    rows.append((middle, [word]))
            for _, row in rows:
                row.sort(key=lambda w: w[0])
                line = ""
                previous = None
                for word in row:
                    if previous is not None:
                        gap = word[0] - previous[2]
                        line += "  |  " if gap > (previous[3] - previous[1]) * 1.2 else " "
                    line += word[4]
                    previous = word
                out.append(line)
            out.append("")
    return "\n".join(out).strip()


# --- Values ------------------------------------------------------------------


def _number(value: Any) -> Decimal | None:
    """A number the model gave, as a Decimal; "R1 913,00"-style strings too."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None
    if not isinstance(value, str):
        return None
    text = re.sub(r"[^\d,.\-]", "", value)
    if not text:
        return None
    # "1.234,56" / "1 234,56": the last separator is the decimal one when it
    # is followed by exactly two digits.
    if "," in text and (text.rfind(",") > text.rfind(".")):
        head, _, tail = text.rpartition(",")
        text = head.replace(".", "").replace(",", "") + ("." + tail if len(tail) == 2 else tail)
    else:
        text = text.replace(",", "")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _money(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(CENT, rounding=ROUND_HALF_UP)


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return str(value)
    return None


_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("jan", "january", "janv", "januar"),
            ("feb", "february", "fev", "fevr", "februar"),
            ("mar", "march", "mars", "marz"),
            ("apr", "april", "avr", "avril"),
            ("may", "mai"),
            ("jun", "june", "juin", "juni"),
            ("jul", "july", "juil", "juillet", "juli"),
            ("aug", "august", "aout"),
            ("sep", "sept", "september", "septembre"),
            ("oct", "october", "octobre", "okt", "oktober"),
            ("nov", "november", "novembre"),
            ("dec", "december", "decembre", "dez", "dezember"),
        ]
    )
    for m in names
}


def _year(value: int) -> int:
    return value + 2000 if value < 100 else value


def parse_date(value: Any, *, month_first: bool = False, today: date | None = None) -> date | None:
    """A printed date. Numeric dates whose order the digits don't settle are
    read day first, or month first when ``month_first``; a date more than a
    week ahead of ``today`` is a misread, not a service."""
    text = _text(value)
    if not text:
        return None
    today = today or date.today()
    text = text.lower().replace(",", " ").replace(".", " ").strip()
    candidates: list[date] = []

    def add(year: int, month: int, day: int) -> None:
        try:
            candidates.append(date(_year(year), month, day))
        except ValueError:
            pass

    if m := re.fullmatch(r"(\d{4})[-/ ](\d{1,2})[-/ ](\d{1,2})(?:[ t].*)?", text):
        add(int(m[1]), int(m[2]), int(m[3]))
    elif m := re.fullmatch(r"(\d{1,2})[-/ ](\d{1,2})[-/ ](\d{2,4})(?: .*)?", text):
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12:
            add(y, b, a)
        elif b > 12:
            add(y, a, b)
        elif month_first:
            add(y, a, b)
        else:
            add(y, b, a)
    else:
        words = re.findall(r"[a-zéû]+|\d+", text)
        month = next(
            (
                _MONTHS[w.replace("é", "e").replace("û", "u")]
                for w in words
                if w.replace("é", "e").replace("û", "u") in _MONTHS
            ),
            None,
        )
        numbers = [int(w) for w in words if w.isdigit()]
        if month and len(numbers) >= 2:
            year = next((n for n in numbers if n > 31), numbers[-1])
            day = next((n for n in numbers if n != year and 1 <= n <= 31), None)
            if day:
                add(year, month, day)
    found = candidates[0] if candidates else None
    if found and (found - today).days > 7:
        return None
    return found


def _normalise_vendor(name: str) -> str:
    name = name.casefold()
    name = re.sub(r"\((pty|pvt)\)", " ", name)
    name = re.sub(r"[^\w\s]", " ", name)
    stop = {"pty", "ltd", "limited", "cc", "inc", "llc", "gmbh", "sarl", "sas", "bv", "co"}
    return " ".join(w for w in name.split() if w not in stop)


def match_vendor(name: str | None, vendors: list[tuple[int, str]]) -> int | None:
    """The address-book vendor this name is, when exactly one fits."""
    if not name:
        return None
    wanted = _normalise_vendor(name)
    if len(wanted) < 3:
        return None
    exact = [vid for vid, vname in vendors if _normalise_vendor(vname) == wanted]
    if len(exact) == 1:
        return exact[0]
    partial = [
        vid
        for vid, vname in vendors
        if (n := _normalise_vendor(vname))
        and len(n) >= 4
        and (n in wanted or wanted in n or n.split()[:2] == wanted.split()[:2])
    ]
    return partial[0] if len(partial) == 1 else None


# --- Lines -------------------------------------------------------------------


@dataclass
class DraftLine:
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    kind: str | None
    cost: Decimal | None = None
    notes: str | None = None


def _kind(value: Any) -> str | None:
    text = (_text(value) or "").casefold()
    text = _KIND_ALIASES.get(text, text)
    return text if text in _LINE_KINDS else None


def _lines(raw: Any) -> list[DraftLine]:
    """The model's lines, with a wrapped description joined to its line and
    the zero lines a job card prints for steps it didn't charge dropped."""
    lines: list[DraftLine] = []
    if not isinstance(raw, list):
        return lines
    for item in raw[: MAX_LINES * 2]:
        if not isinstance(item, dict):
            continue
        description = _text(item.get("description"))
        quantity = _number(item.get("quantity"))
        unit_price = _number(item.get("unit_price"))
        amount = _number(item.get("amount"))
        if not description:
            continue
        if quantity is None and unit_price is None and amount is None and lines:
            # The second line of a description that wrapped.
            lines[-1].description = f"{lines[-1].description} {description}"
            continue
        if (amount is None or amount == 0) and (quantity is None or quantity == 0):
            if not unit_price:
                continue
        lines.append(DraftLine(description, quantity, unit_price, amount, _kind(item.get("kind"))))
    return lines[:MAX_LINES]


def _close(a: Decimal, b: Decimal, lines: int) -> bool:
    """Equal within the rounding a printed table carries: a cent a line, at
    least a rand/dollar."""
    return abs(a - b) <= max(Decimal(1), CENT * lines)


@dataclass
class Reconciled:
    costs: list[Decimal | None]
    tax_amount: Decimal | None
    warnings: list[str] = field(default_factory=list)


def reconcile(
    lines: list[DraftLine],
    *,
    subtotal: Decimal | None,
    tax: Decimal | None,
    total: Decimal | None,
) -> Reconciled:
    """Each line's cost before tax, and the tax, such that they add up to the
    invoice's total.

    Two readings are tried for the lines: the ``amount`` column as given, and
    quantity × unit price. A reading whose sum plus the tax is the total is
    before tax, as asked. A reading whose sum IS the total carries the tax,
    and each line is scaled back by the tax's share (the last line takes
    the rounding), so the visit's total stays the invoice's to the cent.
    """
    n = max(len(lines), 1)
    tax = tax if tax and tax > 0 else None
    if total is None and subtotal is not None:
        total = subtotal + (tax or 0)
    if tax is None and total is not None and subtotal is not None and subtotal < total:
        tax = total - subtotal

    amounts = [line.amount for line in lines]
    products = [
        (line.quantity * line.unit_price)
        if line.quantity is not None and line.unit_price is not None
        else line.amount
        for line in lines
    ]
    readings = [amounts, products] if products != amounts else [amounts]

    def total_of(reading: list[Decimal | None]) -> Decimal:
        return sum((v for v in reading if v is not None), Decimal(0))

    if total is not None:
        for reading in readings:
            if _close(total_of(reading) + (tax or 0), total, n):
                return Reconciled([_money(v) for v in reading], _money(tax))
        if tax:
            for reading in readings:
                if _close(total_of(reading), total, n):
                    return Reconciled(_without_tax(reading, lines, total, tax), _money(tax))

    # Nothing adds up: a line was misread or dropped. Each line on its own
    # then: before tax (taken out at the invoice's rate when the amounts
    # carry it), or quantity × unit price where that agrees. No line absorbs
    # another's difference; the warning says how far off the total is.
    if total is None:
        return Reconciled([_money(v) for v in amounts], _money(tax))
    rate = tax / (total - tax) if tax and total > tax else Decimal(0)
    gross = bool(rate) and _amounts_carry_tax(lines, rate, total_of(amounts), total, tax)
    if not gross:
        rate = Decimal(0)
    costs: list[Decimal | None] = []
    for line in lines:
        base = line.amount / (1 + rate) if line.amount is not None else None
        product = (
            line.quantity * line.unit_price
            if line.quantity is not None and line.unit_price is not None
            else None
        )
        if base is None:
            costs.append(_money(product))
        elif product is not None and abs(product - base) <= abs(base) * Decimal("0.01") + CENT:
            costs.append(_money(product))
        else:
            costs.append(_money(base))
    off = total_of(costs) + (tax or 0) - total
    return Reconciled(
        costs,
        _money(tax),
        [
            f"The lines add up to {total + off:.2f} with tax, the invoice says {total:.2f} "
            f"({off:+.2f}). A line was probably misread or missed: check them before saving."
        ],
    )


def _amounts_carry_tax(
    lines: list[DraftLine], rate: Decimal, amounts_sum: Decimal, total: Decimal, tax: Decimal | None
) -> bool:
    """Whether the ``amount`` column carries tax: a vote of the lines whose
    quantity × unit price is printed (amount ≈ product, or ≈ product with
    tax); without any, whichever reading of the sum is nearer the total."""
    net = gross = 0
    for line in lines:
        if line.amount is None or line.quantity is None or line.unit_price is None:
            continue
        product = line.quantity * line.unit_price
        if not product:
            continue
        if abs(line.amount - product) <= abs(product) * Decimal("0.01") + CENT:
            net += 1
        elif abs(line.amount - product * (1 + rate)) <= abs(product) * Decimal("0.01") + CENT:
            gross += 1
    if net or gross:
        return gross > net
    return abs(amounts_sum - total) < abs(amounts_sum + (tax or 0) - total)


def _without_tax(
    reading: list[Decimal | None], lines: list[DraftLine], total: Decimal, tax: Decimal
) -> list[Decimal | None]:
    """Tax-inclusive line amounts → before tax, summing to ``total - tax``.

    Scaling leaves a cent of drift on lines whose tax was rounded per line,
    so a line whose quantity × unit price agrees with its scaled amount takes
    that exact figure; the rounding left over goes to the largest line that
    didn't agree (or the largest line)."""
    net = (total - tax).quantize(CENT, rounding=ROUND_HALF_UP)
    gross = sum((v for v in reading if v is not None), Decimal(0))
    factor = net / gross if gross else Decimal(1)
    costs: list[Decimal | None] = []
    exact: list[bool] = []
    for value, line in zip(reading, lines, strict=True):
        if value is None:
            costs.append(None)
            exact.append(False)
            continue
        scaled = value * factor
        product = (
            line.quantity * line.unit_price
            if line.quantity is not None and line.unit_price is not None
            else None
        )
        snapped = (
            product is not None and abs(product - scaled) <= abs(scaled) * Decimal("0.001") + CENT
        )
        costs.append(_money(product if snapped else scaled))
        exact.append(snapped)
    rest = net - sum((c for c in costs if c is not None), Decimal(0))
    if rest:
        pool = [i for i, c in enumerate(costs) if c is not None and not exact[i]] or [
            i for i, c in enumerate(costs) if c is not None
        ]
        if pool:
            target = max(pool, key=lambda i: costs[i] or 0)
            costs[target] = (costs[target] or Decimal(0)) + rest
    return costs


def _line_note(line: DraftLine, cost: Decimal | None) -> str | None:
    parts: list[str] = []
    if line.kind and line.kind != "other":
        parts.append(line.kind.capitalize())
    if line.quantity is not None and line.quantity not in (0, 1) and line.quantity > 0:
        qty = f"{line.quantity.normalize():f}"
        # Only a quantity the line's own figures agree with: OCR turns a 1 into a 4.
        if line.unit_price is not None and cost is not None:
            if abs(line.quantity * line.unit_price - cost) <= max(
                abs(cost) * Decimal("0.02"), CENT
            ):
                parts.append(f"{qty} × {_money(cost / line.quantity)}")
        else:
            parts.append(f"qty {qty}")
    return ", ".join(parts) or None


# --- Draft -------------------------------------------------------------------


def build_draft(
    raw: dict[str, Any],
    *,
    vendors: list[tuple[int, str]],
    month_first: bool = False,
    today: date | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """The model's as-printed answer → the draft the form fills from."""
    warnings: list[str] = []
    lines = _lines(raw.get("line_items"))
    total = _number(raw.get("total"))
    tax = _number(raw.get("tax_amount"))
    subtotal = _number(raw.get("subtotal"))
    rec = reconcile(lines, subtotal=subtotal, tax=tax, total=total)
    warnings.extend(rec.warnings)

    odometer = _number(raw.get("odometer"))
    unit = (_text(raw.get("odometer_unit")) or "km").casefold()
    if odometer is not None and odometer > 0:
        if unit.startswith("mi"):
            odometer = odometer * Decimal("1.609344")
        odometer = odometer.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    else:
        odometer = None

    printed_date = _text(raw.get("date"))
    visit_date = parse_date(printed_date, month_first=month_first, today=today)
    if printed_date and visit_date is None:
        warnings.append(f"Could not read the date {printed_date!r}.")

    vendor_name = _text(raw.get("vendor_name"))
    invoice_number = _text(raw.get("invoice_number"))
    draft_lines = []
    for line, cost in zip(lines, rec.costs, strict=True):
        draft_lines.append(
            {
                "description": line.description[:DESCRIPTION_MAX],
                "cost": cost,
                "kind": line.kind,
                "notes": _line_note(line, cost),
            }
        )
    if not draft_lines:
        warnings.append("No lines were read from the invoice.")

    draft = {
        "date": visit_date,
        "odometer_km": odometer,
        "vendor_name": vendor_name,
        "vendor_id": match_vendor(vendor_name, vendors),
        # The visit's own invoice number field (max 50 chars), not the notes.
        "invoice_number": invoice_number[:50] if invoice_number else None,
        "currency": (_text(raw.get("currency")) or "").upper()[:3] or None,
        "tax_amount": rec.tax_amount,
        "total": _money(total),
        "notes": None,
        "line_items": draft_lines,
    }
    return draft, warnings


def _month_first(user: User | None) -> bool:
    """An ambiguous 05/10/2026 is read month first only for someone who both
    chose month-first dates and counts in dollars; everywhere else that
    prints invoices this way reads it day first."""
    return bool(
        user is not None
        and getattr(user, "date_format", "mdy") == "mdy"
        and (getattr(user, "currency_code", None) or "USD") == "USD"
    )


async def _ocr(file_bytes: bytes, filename: str | None, content_type: str | None) -> str:
    """Tesseract's text for a photo or scan; "" when OCR is missing or fails.

    The pages go through `document_images` first, the same as for the vision
    model: a phone photo is turned upright (EXIF), a HEIC opened, a scanned
    PDF rasterised. The size is kept higher than for a model, for the print.
    """
    from app.services.document_ocr import DocumentOCRService

    try:
        images = await asyncio.to_thread(
            to_images,
            file_bytes,
            filename,
            content_type,
            max_pages=MAX_PAGES,
            max_side=2400,
            quality=92,
            max_total_bytes=20_000_000,
        )
        ocr = DocumentOCRService()
        pages = [await ocr.extract_text_from_bytes(image, is_pdf=False) for image, _ in images]
    except Exception as exc:  # noqa: BLE001 - OCR backends raise broadly
        logger.info("Invoice OCR failed (%s)", sanitize_for_log(str(exc)))
        return ""
    return "\n\n".join(p.strip() for p in pages if p and p.strip())


async def _vendors(db: AsyncSession) -> list[tuple[int, str]]:
    result = await db.execute(select(Vendor.id, Vendor.name))
    return [(row[0], row[1]) for row in result.all() if row[1]]


async def read_service_invoice(
    db: AsyncSession,
    *,
    file_bytes: bytes,
    filename: str | None,
    content_type: str | None,
    user: User | None,
    allow_external_vision: bool = False,
) -> dict[str, Any]:
    """See the module docstring. Returns ``{draft, source, model, warnings}``."""
    if not await document_reader_service.reading_enabled(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=document_reader_service.AI_READING_NOT_CONFIGURED,
        )

    prompt = prompt_for(KIND)
    text = ""
    source = "text"
    pdf = is_pdf(filename, content_type)
    if pdf and await asyncio.to_thread(has_text_layer, file_bytes):
        try:
            text = await asyncio.to_thread(layout_text, file_bytes)
        except Exception as exc:  # noqa: BLE001 - a broken PDF falls back to OCR
            logger.info("Invoice text layer unreadable (%s)", sanitize_for_log(str(exc)))
            text = ""
    if not text:
        text = await _ocr(file_bytes, filename, content_type)
        source = "ocr"
        if len(text) < MIN_OCR_CHARS:
            text = ""

    if text:
        await llm_client.require_vision_consent(db, allow_external=allow_external_vision)
        content = await llm_client.chat_completion(
            db,
            system=prompt.system,
            user=f"{prompt.user_text}\n\nDocument text:\n{text[:MAX_TEXT_CHARS]}",
            temperature=0,
            timeout=prompt.timeout,
        )
        raw = llm_client.extract_json_object(str(content))
        fields, warnings = document_reader_service.coerce_fields(raw, prompt.keys)
        model = await llm_client.setting(db, llm_client.LLM_MODEL_SETTING, llm_client.DEFAULT_MODEL)
    else:
        read = await document_reader_service.read_document(
            db,
            kind=KIND,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
            allow_external_vision=allow_external_vision,
        )
        fields, warnings, source, model = dict(read.fields), list(read.warnings), "llm", read.model

    draft, draft_warnings = build_draft(
        fields,
        vendors=await _vendors(db),
        month_first=_month_first(user),
        today=datetime.now().date(),
    )
    warnings.extend(draft_warnings)
    logger.info(
        "Service invoice read from %s by %s: %d line(s), %d warning(s)",
        source,
        sanitize_for_log(str(model)),
        len(draft["line_items"]),
        len(warnings),
    )
    return {"draft": draft, "source": source, "model": model, "warnings": warnings}
