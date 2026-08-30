"""The one hours formatter: the quantity that sits outside the unit system.

R6: hours are dimensionless. ``"hours"`` is not a ``UnitSet`` field, so
``adapter_for(..., "hours")`` raises ``KeyError`` by design and there is no
counterpart to show. This fixed ``"hr"`` formatter is therefore deliberately
NOT routed through ``unit_formatting``; the "every rendering site uses the
formatting layer" rule does not reach it, and neither does ``RenderContext``,
because there is nothing here for a unit preference to decide.

Its own module rather than a private helper inside either consumer, because
the same stored field reaches readers two ways -- a reminder's ``due_hours``
renders in the vehicle PDF (``pdf_vehicle_report._reminder_due_text``) and in
the due-reminder notification (``reminder_service._build_reminder_message``)
-- and two private copies could drift into two different strings for one
value. One definition also keeps this exception to the formatting-layer rule
in a single auditable place.
"""

from __future__ import annotations

from decimal import Decimal


def format_hours(hours: Decimal | None) -> str:
    """Render an hours figure, or ``"N/A"`` when there is none.

    One decimal place, thousands-grouped, with a fixed ``hr`` label that no
    unit preference can change.
    """
    if hours is None:
        return "N/A"
    return f"{hours:,.1f} hr"
