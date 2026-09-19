"""What insurance actually cost, per vehicle, over a span of days.

`insurance_shares` answers "what is this vehicle's share per billing period".
This module turns that into money over time, and it is the ONLY place that
does, so garage analytics, the garage PDF (which renders from the same
analytics call) and the per-vehicle export cannot disagree.

Intervals are HALF-OPEN, `[start, end)`. Declarations pages print adjacent
terms with a shared boundary date (one term ends 07-01, the next starts 07-01);
half-open intervals mean that day is counted once.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")

#: Approximate days per billing period, used only to COUNT the periods in a
#: term (a 181-day and a 184-day "six month" policy are both one Semi-Annual
#: period and both six Monthly ones).
_PERIOD_DAYS = {
    "Monthly": Decimal("30.4375"),
    "Quarterly": Decimal("91.3125"),
    "Semi-Annual": Decimal("182.625"),
    "Annual": Decimal("365.25"),
}


def periods_in_term(frequency: str | None, start: date, end: date) -> int:
    """How many billing periods the term holds. At least one.

    An unknown frequency means the stored amount was simply "the premium", so
    it counts once for the term.
    """
    period_days = _PERIOD_DAYS.get(frequency or "")
    term_days = (end - start).days
    if period_days is None or term_days <= 0:
        return 1
    return max(1, int((Decimal(term_days) / period_days).quantize(Decimal("1"), ROUND_HALF_UP)))


def term_cost(share: Decimal | None, frequency: str | None, start: date, end: date) -> Decimal:
    """One vehicle's cost for the whole term."""
    if share is None:
        return Decimal("0.00")
    return (share * periods_in_term(frequency, start, end)).quantize(CENT)


def cost_between(
    share: Decimal | None,
    frequency: str | None,
    start: date,
    end: date,
    window_start: date,
    window_end: date,
    effective_to: date | None = None,
) -> Decimal:
    """The part of a vehicle's term cost that falls in `[window_start, window_end)`.

    `effective_to` ends the vehicle's cover early (it left the policy mid-term).
    The term cost is spread evenly over the term's days.
    """
    term_days = (end - start).days
    whole = term_cost(share, frequency, start, end)
    if whole == 0:
        return whole
    covered_end = min(end, effective_to) if effective_to is not None else end
    if term_days <= 0:
        return whole if window_start <= start < window_end else Decimal("0.00")
    overlap_start = max(start, window_start)
    overlap_end = min(covered_end, window_end)
    overlap_days = (overlap_end - overlap_start).days
    if overlap_days <= 0:
        return Decimal("0.00")
    return (whole * overlap_days / term_days).quantize(CENT, ROUND_HALF_UP)


def monthly_costs(
    share: Decimal | None,
    frequency: str | None,
    start: date,
    end: date,
    until: date,
    effective_to: date | None = None,
) -> dict[tuple[int, int], Decimal]:
    """`{(year, month): cost}` for the cover that has accrued before `until`."""
    result: dict[tuple[int, int], Decimal] = {}
    cursor = date(start.year, start.month, 1)
    stop = min(end, until)
    while cursor < stop:
        following = date(cursor.year + cursor.month // 12, cursor.month % 12 + 1, 1)
        amount = cost_between(
            share, frequency, start, end, cursor, min(following, until), effective_to
        )
        if amount:
            result[(cursor.year, cursor.month)] = amount
        cursor = following
    return result


def accrued_cost(
    share: Decimal | None,
    frequency: str | None,
    start: date,
    end: date,
    today: date,
    effective_to: date | None = None,
) -> Decimal:
    """Cost to date: everything up to and including today."""
    return cost_between(
        share, frequency, start, end, date.min, today + timedelta(days=1), effective_to
    )
