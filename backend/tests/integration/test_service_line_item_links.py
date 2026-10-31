"""The inspection link relationships point the way their names say (S1d-05).

`triggered_by_inspection` is the one inspection a repair came from, and
`triggered_repairs` is the list of repairs an inspection set off. They used to
be the other way round.
"""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.service_line_item import ServiceLineItem
from app.models.service_visit import ServiceVisit


@pytest.mark.asyncio
async def test_repair_points_at_its_inspection_and_inspection_lists_its_repairs(
    db_session: AsyncSession,
    test_sessionmaker: async_sessionmaker[AsyncSession],
    test_vehicle: dict[str, object],
) -> None:
    """A repair's link is the inspection itself; the inspection's is a list of repairs."""
    vin = str(test_vehicle["vin"])
    visit = ServiceVisit(vin=vin, date=dt.date(2026, 3, 1))
    db_session.add(visit)
    await db_session.flush()
    inspection = ServiceLineItem(
        visit_id=visit.id,
        description="Brake inspection",
        is_inspection=True,
        inspection_result="needs_attention",
        inspection_severity="yellow",
    )
    db_session.add(inspection)
    await db_session.flush()
    repair = ServiceLineItem(
        visit_id=visit.id,
        description="Front pads",
        triggered_by_inspection_id=inspection.id,
    )
    db_session.add(repair)
    await db_session.commit()
    visit_id, inspection_id, repair_id = visit.id, inspection.id, repair.id

    try:
        # Fresh session so nothing comes out of the writer's identity map.
        async with test_sessionmaker() as read:
            rows = (
                await read.execute(
                    select(ServiceLineItem)
                    .where(ServiceLineItem.visit_id == visit_id)
                    .options(
                        selectinload(ServiceLineItem.triggered_by_inspection),
                        selectinload(ServiceLineItem.triggered_repairs),
                    )
                )
            ).scalars()
            by_id = {row.id: row for row in rows}
            loaded_inspection = by_id[inspection_id]
            loaded_repair = by_id[repair_id]

            assert loaded_repair.triggered_by_inspection is loaded_inspection
            assert loaded_inspection.triggered_repairs == [loaded_repair]
            assert loaded_inspection.triggered_by_inspection is None
            assert loaded_repair.triggered_repairs == []
    finally:
        await db_session.delete(await db_session.get(ServiceVisit, visit_id))
        await db_session.commit()
