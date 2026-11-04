"""Every PDF route prints dates in the reader's order (#278).

The page sends `date_format` (what it shows); without it the account decides.
"""

import re
from datetime import UTC, datetime, tzinfo

import pymupdf
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.utils import pdf_components, pdf_generator

PERIOD = {"start_date": "2026-01-02", "end_date": "2026-12-03"}
# The report body's "Report Generated" line, numeric date and a 12-hour clock.
GENERATED = re.compile(r"\b(\d{2})/(\d{2})/\d{4} \d{2}:\d{2} [AP]M\b")
# Midday on Oct 4: day and month differ, and it's Oct 4 in any zone within 11 hours of UTC.
FROZEN = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:  # type: ignore[override]
        return FROZEN.astimezone(tz) if tz is not None else FROZEN.replace(tzinfo=None)


def _text(pdf: bytes) -> str:
    document = pymupdf.open(stream=pdf, filetype="pdf")
    text = " ".join(page.get_text() for page in document)  # type: ignore[operator]
    document.close()
    return text


async def _set_account(db: AsyncSession, user_id: object, **fields: str) -> None:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one()
    for name, value in fields.items():
        setattr(user, name, value)
    await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
class TestReportDateOrder:
    async def test_the_page_asks_for_day_first(
        self, client: AsyncClient, auth_headers, test_vehicle
    ) -> None:
        r = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf",
            headers=auth_headers,
            params={**PERIOD, "date_format": "dmy"},
        )
        assert r.status_code == 200, r.text
        assert "02/01/2026 - 03/12/2026" in _text(r.content)

    async def test_without_a_request_the_account_decides(
        self, client: AsyncClient, auth_headers, test_vehicle, test_user, db_session
    ) -> None:
        url = f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf"
        try:
            r = await client.get(url, headers=auth_headers, params=PERIOD)
            assert "01/02/2026 - 12/03/2026" in _text(r.content)

            await _set_account(db_session, test_user["id"], date_format="dmy")
            r = await client.get(url, headers=auth_headers, params=PERIOD)
            assert "02/01/2026 - 03/12/2026" in _text(r.content)
        finally:
            await _set_account(db_session, test_user["id"], date_format="mdy")

    async def test_another_language_reads_day_first(
        self, client: AsyncClient, auth_headers, test_vehicle, test_user, db_session
    ) -> None:
        url = f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf"
        before = (
            await db_session.execute(select(User.language).where(User.id == test_user["id"]))
        ).scalar_one()
        try:
            await _set_account(db_session, test_user["id"], language="de")
            r = await client.get(url, headers=auth_headers, params=PERIOD)
            assert "02/01/2026 - 03/12/2026" in _text(r.content)
        finally:
            await _set_account(db_session, test_user["id"], language=before)

    @pytest.mark.parametrize(
        "path",
        [
            "service-history-pdf",
            "sale-history-pdf",
            "cost-summary-pdf?year=2026",
            "tax-deduction-pdf?year=2026",
        ],
    )
    async def test_every_vehicle_report_takes_it(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(pdf_generator, "datetime", _FrozenDatetime)
        base = f"/api/vehicles/{test_vehicle['vin']}/reports/{path}"
        sep = "&" if "?" in path else "?"
        days = []
        for order in ("mdy", "dmy"):
            r = await client.get(f"{base}{sep}date_format={order}", headers=auth_headers)
            assert r.status_code == 200, r.text
            match = GENERATED.search(_text(r.content))
            assert match, path
            days.append(match.groups())
        assert days == [("10", "04"), ("04", "10")], path

    async def test_an_unknown_order_is_a_422(
        self, client: AsyncClient, auth_headers, test_vehicle
    ) -> None:
        r = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf",
            headers=auth_headers,
            params={"date_format": "ymd"},
        )
        assert r.status_code == 422, r.text
        assert "string_pattern_mismatch" in r.text, r.text

    @pytest.mark.parametrize("which", ["vehicle", "garage"])
    async def test_analytics_pdfs_take_it(
        self,
        client: AsyncClient,
        auth_headers,
        test_vehicle,
        which: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        url = (
            f"/api/analytics/vehicles/{test_vehicle['vin']}/export"
            if which == "vehicle"
            else "/api/analytics/garage/export"
        )
        monkeypatch.setattr(pdf_components, "datetime", _FrozenDatetime)
        dmy = await client.get(url, headers=auth_headers, params={"date_format": "dmy"})
        mdy = await client.get(url, headers=auth_headers, params={"date_format": "mdy"})
        assert dmy.status_code == 200, dmy.text
        assert mdy.status_code == 200, mdy.text
        # The branded header's date, exact, so residue text in the shared DB can't interfere.
        assert "04 October 2026" in _text(dmy.content)
        assert "October 04, 2026" not in _text(dmy.content)
        assert "October 04, 2026" in _text(mdy.content)

    async def test_with_auth_off_the_page_decides(
        self, client: AsyncClient, test_vehicle, set_auth_mode
    ) -> None:
        # No account to read, so what the page sends is the only answer.
        await set_auth_mode("none")
        r = await client.get(
            f"/api/vehicles/{test_vehicle['vin']}/reports/service-history-pdf",
            params={**PERIOD, "date_format": "dmy"},
        )
        assert r.status_code == 200, r.text
        assert "02/01/2026 - 03/12/2026" in _text(r.content)
