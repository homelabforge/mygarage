"""Defense-in-depth test for the gas_station vendor-sync bypass (issue #69).

The fuel-record save path creates `address_book` entries with
`poi_category='gas_station'` for newly-typed station names. These entries
must NOT propagate into the `vendors` table, which holds service-shop
contacts (a different domain object). The guard lives in
`routes/address_book.py::_sync_to_vendor`.
"""

from __future__ import annotations

import pytest

from app.routes.address_book import _sync_to_vendor


class _FakeEntry:
    """Minimal stand-in for AddressBookEntry — the guard only reads
    `poi_category` and short-circuits before touching any DB session."""

    def __init__(self, *, business_name: str, poi_category: str | None = None) -> None:
        self.business_name = business_name
        self.poi_category = poi_category
        self.address = None
        self.city = None
        self.state = None
        self.zip_code = None
        self.phone = None


class _SessionRecorder:
    """Fails loudly if the guard tries to touch the DB."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def begin_nested(self):  # pragma: no cover - exercised when guard fails
        self.calls.append("begin_nested")
        raise AssertionError("gas_station entries must not enter the vendor-sync transaction")


@pytest.mark.asyncio
async def test_gas_station_entry_skips_vendor_sync():
    """A poi_category='gas_station' entry must short-circuit the helper."""
    entry = _FakeEntry(business_name="Costco Gas #42", poi_category="gas_station")
    db = _SessionRecorder()
    await _sync_to_vendor(db, entry.business_name, entry)  # type: ignore[arg-type]
    # The recorder explodes on any DB call; reaching here means the guard fired.
    assert db.calls == []


@pytest.mark.asyncio
async def test_blank_business_name_short_circuits_first():
    """Blank business names short-circuit ahead of the poi_category guard."""
    entry = _FakeEntry(business_name="   ", poi_category="auto_shop")
    db = _SessionRecorder()
    await _sync_to_vendor(db, "   ", entry)  # type: ignore[arg-type]
    assert db.calls == []
