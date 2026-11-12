"""An audit row's `details` is a dict or nothing.

The SSO link step stored a sentence there while every other writer stored a
JSON object, so a reader of the column couldn't count on its shape. The model
now refuses anything else when it's assigned. Loading doesn't run the check, so
the sentence rows already in a database still read.
"""

import uuid

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


@pytest.mark.parametrize("bad", ["x", ["reason"], 3], ids=["str", "list", "int"])
def test_details_refuses_anything_but_a_dict(bad: object) -> None:
    with pytest.raises(TypeError):
        AuditLog(action="test", details=bad)


def test_assigning_details_later_is_checked_too() -> None:
    row = AuditLog(action="test")

    with pytest.raises(TypeError):
        row.details = "x"  # pyright: ignore[reportAttributeAccessIssue]  # deliberately invalid


def test_details_takes_a_dict_or_none() -> None:
    assert AuditLog(action="test", details={"reason": "x"}).details == {"reason": "x"}
    assert AuditLog(action="test", details=None).details is None


@pytest.mark.asyncio
async def test_an_old_row_with_a_string_still_loads(db_session: AsyncSession) -> None:
    """A Core insert skips the validator, like the rows written before it existed."""
    action = f"legacy_{uuid.uuid4().hex[:10]}"
    await db_session.execute(insert(AuditLog).values(action=action, details="Linked OIDC account"))
    await db_session.commit()
    try:
        row = (
            await db_session.execute(select(AuditLog).where(AuditLog.action == action))
        ).scalar_one()
        assert row.details == "Linked OIDC account"
    finally:
        await db_session.rollback()
        await db_session.execute(delete(AuditLog).where(AuditLog.action == action))
        await db_session.commit()
