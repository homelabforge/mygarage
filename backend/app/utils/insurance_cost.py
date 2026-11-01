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


#: Calendar months between one billing date and the next.
_STEP_MONTHS = {"Monthly": 1, "Quarterly": 3, "Semi-Annual": 6, "Annual": 12}


def add_months(day: date, months: int) -> date:
    """`day` moved forward by whole calendar months, clamped to the month's last day.

    Counted from the original date every time, never chained, so a policy that
    starts on the 31st is billed on Jan 31, Feb 28 (29 in a leap year), Mar 31,
    Apr 30 and so on, instead of drifting to the 28th for the rest of the term.
    """
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def billing_periods(frequency: str | None, start: date, end: date) -> list[tuple[date, date]]:
    """The term cut into its billing periods, as `[start, end)` pairs.

    Periods begin on the policy's calendar anniversaries (see `add_months`), the
    way a bill actually falls, and the count is `periods_in_term`, so this and
    `term_cost` always agree on how many payments the term holds. The first
    period starts on `start` and the last ends on `end`.
    """
    count = periods_in_term(frequency, start, end)
    step = _STEP_MONTHS.get(frequency or "")
    if count == 1 or step is None:
        return [(start, end)]
    starts = [min(add_months(start, k * step), end) for k in range(count)]
    return list(zip(starts, [*starts[1:], end], strict=True))


def paid_cost(
    share: Decimal | None,
    frequency: str | None,
    start: date,
    end: date,
    today: date,
    effective_to: date | None = None,
) -> Decimal:
    """Cost counting each billing period in full once it has begun.

    This is how an expense logged whole on the day it is paid reads. A Monthly
    policy with a twelve-month term has cost three payments once its third month
    has begun, not twelve; a Semi-Annual or Annual policy that holds a single
    period counts it whole from its start date. A policy that has not started
    yet costs nothing. If the vehicle's cover ended early (`effective_to`), the
    periods it never reached cost nothing and the one it ended inside is
    prorated by that period's own days, so a payment is not counted for cover
    the vehicle no longer had.

    Billing periods here and the term `cost_between` spreads over days are the
    same term with the same period count; they differ only in how the money is
    placed (whole at the start of each period here, evenly by day there).
    """
    if share is None or start > today:
        return Decimal("0.00")
    total = Decimal("0.00")
    for period_start, period_end in billing_periods(frequency, start, end):
        if period_start > today:
            break
        if effective_to is None or effective_to >= period_end:
            total += share
        elif effective_to > period_start and period_end > period_start:
            days = Decimal((period_end - period_start).days)
            total += share * Decimal((effective_to - period_start).days) / days
        elif period_end <= period_start and effective_to >= period_start:
            # A term whose end is on or before its start (bad or placeholder
            # dates) is one period with no days to prorate, so it counts whole
            # if the vehicle's cover reached its date and not at all otherwise.
            total += share
    return total.quantize(CENT, ROUND_HALF_UP)
