"""A file usage with no cost matches its stored usage once that's priced (#301).

A backup taken before its supplies had a cost carries usages with no snapshots.
Migration 161, or the import's own pricing pass, prices the stored copy, so a
re-import has to see the same visit, not write a second one.
"""

from collections import Counter
from decimal import Decimal
from typing import Any

from app.routes.import_data._service import _items_match, _usages_match, usage_counts


def _usages(
    *rows: tuple[str, str, str | None, str | None],
) -> frozenset[tuple[tuple[Any, ...], int]]:
    """(name, quantity, unit cost, cost) rows as one item's usage counts."""
    return usage_counts(
        (
            name,
            None,
            "volume",
            Decimal(quantity),
            None if unit is None else Decimal(unit),
            None if cost is None else Decimal(cost),
        )
        for name, quantity, unit, cost in rows
    )


OIL_UNPRICED = ("oil", "4.4", None, None)
OIL_PRICED = ("oil", "4.4", "6.3401", "27.90")
OIL_DEARER = ("oil", "4.4", "7.0455", "31.00")


def test_an_unpriced_file_usage_matches_the_priced_stored_one():
    assert _usages_match(_usages(OIL_UNPRICED), _usages(OIL_PRICED))


def test_an_unpriced_file_usage_still_needs_the_same_quantity():
    assert not _usages_match(_usages(OIL_UNPRICED), _usages(("oil", "5", "6.3401", "31.70")))


def test_an_unpriced_file_usage_still_needs_the_same_supply():
    assert not _usages_match(_usages(OIL_UNPRICED), _usages(("coolant", "4.4", "6.3401", "27.90")))


def test_a_priced_file_usage_still_needs_its_own_price():
    assert not _usages_match(_usages(OIL_PRICED), _usages(OIL_DEARER))


def test_a_stored_usage_the_file_doesnt_have_is_no_match():
    assert not _usages_match(_usages(OIL_UNPRICED), _usages(OIL_PRICED, OIL_PRICED))
    assert not _usages_match(_usages(OIL_UNPRICED), _usages())


def test_priced_and_unpriced_copies_pair_up():
    assert _usages_match(_usages(OIL_UNPRICED, OIL_PRICED), _usages(OIL_DEARER, OIL_PRICED))


def _item(usages: frozenset[tuple[tuple[Any, ...], int]]) -> tuple[Any, ...]:
    return ("Oil change", Decimal("10.00"), usages)


def test_an_item_that_takes_the_wrong_partner_first_gives_it_up():
    # The unpriced item fits either stored one; the priced one fits only the
    # first. Taken in file order, the unpriced item has to move over.
    file = Counter([_item(_usages(OIL_UNPRICED)), _item(_usages(OIL_PRICED))])
    stored = Counter([_item(_usages(OIL_PRICED)), _item(_usages(OIL_DEARER))])
    assert _items_match(file, stored)


def test_items_with_nothing_to_pair_are_no_match():
    file = Counter([_item(_usages(OIL_PRICED)), _item(_usages(OIL_PRICED))])
    stored = Counter([_item(_usages(OIL_PRICED)), _item(_usages(OIL_DEARER))])
    assert not _items_match(file, stored)
    assert not _items_match(Counter([_item(_usages(OIL_UNPRICED))]), Counter())
