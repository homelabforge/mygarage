"""Each insurance test reads and deletes only the policies it made.

A policy is a household row, and some have no vehicle at all, so neither a VIN
nor an owner can scope one. Ids only grow (a PG sequence, SQLite's next rowid
above the current max), so "made by this test" is "id above the highest one
there was when the test started". Emptying the table instead would also
delete other tests' leaked rows before the leak guard saw them.
"""

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.insurance import InsurancePolicy


class PolicyScope:
    """The running test's policies: `start` it in a fixture, `drop` them after."""

    def __init__(self) -> None:
        self.floor = 0

    async def start(self, db: AsyncSession) -> None:
        self.floor = await db.scalar(select(func.max(InsurancePolicy.id))) or 0

    def mine(self) -> ColumnElement[bool]:
        return InsurancePolicy.id > self.floor

    async def drop(self, db: AsyncSession) -> None:
        """Delete this test's policies (their links and fields go by cascade). No commit."""
        await db.execute(delete(InsurancePolicy).where(self.mine()))
