"""Each insurance test reads and deletes only the policies it made.

A policy is a household row, and some have no vehicle at all, so neither a VIN
nor an owner can scope one. Ids only grow (a PG sequence, SQLite's next rowid
above the current max), so "made by this test" is "id above the highest one
there was when the test started". Emptying the table instead would also
delete other tests' leaked rows before the leak guard saw them.
"""

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import (
    InsuranceCoverage,
    InsurancePolicy,
    InsurancePolicyField,
    InsurancePolicyVehicle,
)


class PolicyScope:
    """The running test's policies: `start` it in a fixture, `drop` them after."""

    def __init__(self) -> None:
        self.floor = 0

    async def start(self, db: AsyncSession) -> None:
        self.floor = await db.scalar(select(func.max(InsurancePolicy.id))) or 0

    def mine(self) -> ColumnElement[bool]:
        return InsurancePolicy.id > self.floor

    async def drop(self, db: AsyncSession) -> None:
        """Delete this test's policies and everything under them. No commit.

        Child first, each through the ORM with `synchronize_session="fetch"`, so
        every deleted row also leaves the session. Leaving the children to the
        database cascade kept them in the identity map, and when SQLite handed
        their ids to the next import's rows the session met two objects with
        one identity (SAWarning: "Identity map already had an identity").
        """
        links = select(InsurancePolicyVehicle.id).where(
            InsurancePolicyVehicle.policy_id > self.floor
        )
        for statement in (
            delete(InsuranceCoverage).where(InsuranceCoverage.policy_vehicle_id.in_(links)),
            delete(InsurancePolicyField).where(InsurancePolicyField.policy_id > self.floor),
            delete(InsurancePolicyVehicle).where(InsurancePolicyVehicle.policy_id > self.floor),
            delete(InsurancePolicy).where(self.mine()),
        ):
            await db.execute(statement.execution_options(synchronize_session="fetch"))
