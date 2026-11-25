"""The prompt for a workshop document: a service or tax invoice, a job card,
a repair quote.

The answer is a draft service visit: the workshop, the date and odometer as
printed, the tax and invoice totals, and every printed line with its
quantity, unit price and amount. The model is asked for values as printed;
`service_invoice_service` parses the date, converts the odometer and checks
the lines against the totals, because a small model copies the wrong column
more often than it misreads a number.
"""

from __future__ import annotations

from app.services.document_prompts import DocumentPrompt

KEYS: tuple[str, ...] = (
    "invoice_number",
    "date",
    "vendor_name",
    "odometer",
    "odometer_unit",
    "currency",
    "subtotal",
    "tax_amount",
    "total",
    "line_items",
)

SYSTEM = (
    "You read a vehicle workshop document: a service invoice, tax invoice, job card or "
    "repair quote.\n"
    "Reply with ONLY a JSON object, no prose, using exactly these keys: " + ", ".join(KEYS) + ".\n"
    "Key meanings: invoice_number = the invoice, quote or job number as printed; "
    "date = the document date exactly as printed (do not reformat it); "
    "vendor_name = the workshop or company that issued the document (the 'From' side, "
    "never the customer); "
    "odometer = the vehicle's mileage or odometer reading as a number, odometer_unit = km "
    "or mi; currency = the ISO 4217 code of the amounts; "
    "subtotal = the total before tax; tax_amount = the tax or VAT total; total = the final "
    "amount including tax; "
    "line_items = a list with one object per printed line, in order, each "
    "{description, quantity, unit_price, amount, kind}: description = the text as printed; "
    "quantity = the quantity, hours or litres as a number; unit_price = the price per unit; "
    "amount = the line's amount BEFORE tax: when a line shows Sub Total, VAT and Total "
    "columns, amount is the Sub Total, never the Total; "
    "kind = labour, part, fee or other.\n"
    "Every number without currency symbols, units or thousands separators (R1 913.00 is "
    "1913.00). Leave out lines whose quantity and amount are both 0. Use null for a value "
    "that is not printed. Never guess, never invent a line; copy what is printed."
)

USER_TEXT = "Read this workshop document and return the JSON object."

PROMPT = DocumentPrompt(
    kind="service_invoice",
    system=SYSTEM,
    user_text=USER_TEXT,
    keys=KEYS,
    # A 25-line invoice is ~1 400 tokens of JSON; the default 2 000 cut the
    # longer ones off mid-list.
    max_tokens=6000,
    timeout=300.0,
)
