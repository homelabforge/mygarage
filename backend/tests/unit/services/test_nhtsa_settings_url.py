"""The stored NHTSA API URL setting: blank means "use the default".

`nhtsa_recalls_api_url` is nullable text in the settings table. A blank or NULL one used to go through the SSRF check, fail it
and log an ERROR before falling back, so every recall check on an install that
never set a URL logged a security block.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import Setting
from app.services.nhtsa import DEFAULT_RECALLS_API_URL, NHTSAService

pytestmark = pytest.mark.asyncio

LOGGER = "app.services.nhtsa"

# (fetch method, setting key, what the default URL's request starts with)
FETCHES = [
    pytest.param(
        "get_vehicle_recalls",
        "nhtsa_recalls_api_url",
        "https://api.nhtsa.gov/recalls/recallsByVehicle?",
        id="recalls",
    ),
]


class _FakeResponse:
    """Just enough of an httpx response for the fetches."""

    status_code = 200

    def raise_for_status(self) -> None:
        """Never an HTTP error."""

    def json(self) -> dict[str, Any]:
        """No recalls."""
        return {"results": []}


@pytest.fixture
def requested(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every URL the service asks httpx for. No network: the HTTP call is
    stubbed, VIN decoding is stubbed, and the SSRF check's DNS lookup is off
    (an unresolvable host is allowed through to the domain allowlist anyway)."""
    urls: list[str] = []

    async def fake_get(self: object, url: str, **kwargs: object) -> _FakeResponse:
        urls.append(url)
        return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.utils.url_validation.resolve_hostname", lambda hostname: None)
    monkeypatch.setattr(
        NHTSAService,
        "decode_vin",
        AsyncMock(return_value={"make": "Honda", "model": "Accord", "year": 2020}),
    )
    return urls


@asynccontextmanager
async def _stored(db: AsyncSession, key: str, value: str | None) -> AsyncIterator[None]:
    """Store `value` for one setting with raw SQL, then put things back.

    The row is the test's own: created here and deleted after. If something
    already seeded the key, its value is restored instead.
    """
    existing = await db.get(Setting, key)
    original = existing.value if existing is not None else None
    if existing is None:
        db.add(Setting(key=key, value="https://api.nhtsa.gov/placeholder", category="integrations"))
        await db.commit()
    try:
        await db.execute(
            text("UPDATE settings SET value = :value WHERE key = :key"),
            {"key": key, "value": value},
        )
        await db.commit()
        db.expire_all()
        yield
    finally:
        await db.rollback()
        if existing is None:
            await db.execute(delete(Setting).where(Setting.key == key))
        else:
            await db.execute(
                text("UPDATE settings SET value = :value WHERE key = :key"),
                {"key": key, "value": original},
            )
        await db.commit()


def _errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Every ERROR the fetch logged."""
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.parametrize("stored", ["", "   ", None], ids=["empty", "spaces", "null"])
@pytest.mark.parametrize(("method", "key", "default_request"), FETCHES)
async def test_a_blank_stored_url_quietly_uses_the_default(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    requested: list[str],
    method: str,
    key: str,
    default_request: str,
    stored: str | None,
) -> None:
    """Blank is nobody having set one, not an SSRF attempt worth an ERROR.

    The URL half is a guard (the old SSRF fallback already landed on the
    default); mutant: remove the except branch, checked on the old code.
    """
    caplog.set_level(logging.WARNING, logger=LOGGER)
    async with _stored(db_session, key, stored):
        await getattr(NHTSAService(), method)("1HGCM82633A123456", db_session)

    assert len(requested) == 1
    assert requested[0].startswith(default_request), requested[0]
    assert _errors(caplog) == []


_DEFAULTS = {
    "nhtsa_recalls_api_url": DEFAULT_RECALLS_API_URL,
}


@pytest.mark.parametrize("which", ["default", "mirror"])
@pytest.mark.parametrize(("method", "key", "default_request"), FETCHES)
async def test_a_stored_url_with_outer_spaces_is_used_stripped(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    requested: list[str],
    method: str,
    key: str,
    default_request: str,
    which: str,
) -> None:
    """Spaces round a pasted URL aren't part of it. Unstripped, the padded URL
    passed the SSRF check (urlparse drops the leading spaces) and httpx then
    refused it, so the check failed before any request.

    The mirror base proves the stored URL is the one fetched, not the default.
    """
    base = _DEFAULTS[key] if which == "default" else "https://api.nhtsa.gov/mirror"
    caplog.set_level(logging.WARNING, logger=LOGGER)
    async with _stored(db_session, key, f"  {base}  "):
        await getattr(NHTSAService(), method)("1HGCM82633A123456", db_session)

    assert len(requested) == 1
    assert requested[0].startswith(base), requested[0]
    assert _errors(caplog) == []


@pytest.mark.parametrize(
    ("stored", "base"),
    [
        pytest.param(
            "https://api.nhtsa.gov/recalls/recallsByVehicle",
            "https://api.nhtsa.gov/recalls",
            id="endpoint",
        ),
        pytest.param(
            "https://api.nhtsa.gov/recalls/recallsByVehicle/",
            "https://api.nhtsa.gov/recalls",
            id="trailing-slash",
        ),
        pytest.param(
            "  https://api.nhtsa.gov/recalls/recallsByVehicle  ",
            "https://api.nhtsa.gov/recalls",
            id="padded",
        ),
        pytest.param(
            "https://api.nhtsa.gov/mirror/recallsByVehicle",
            "https://api.nhtsa.gov/mirror",
            id="mirror",
        ),
    ],
)
async def test_a_stored_recalls_endpoint_reads_as_its_base(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    requested: list[str],
    stored: str,
    base: str,
) -> None:
    """The Integrations tab used to save the full endpoint, and the fetch adds
    /recallsByVehicle itself, so it asked for the path twice. Rows saved that
    way keep working without a migration. The mirror shows the suffix is
    trimmed, not the value swapped for the default."""
    caplog.set_level(logging.WARNING, logger=LOGGER)
    async with _stored(db_session, "nhtsa_recalls_api_url", stored):
        await NHTSAService().get_vehicle_recalls("1HGCM82633A123456", db_session)

    assert len(requested) == 1
    assert requested[0].startswith(f"{base}/recallsByVehicle?"), requested[0]
    assert requested[0].count("recallsByVehicle") == 1, requested[0]
    assert _errors(caplog) == []


@pytest.mark.parametrize(("method", "key", "default_request"), FETCHES)
async def test_a_stored_url_is_still_used(
    db_session: AsyncSession,
    requested: list[str],
    method: str,
    key: str,
    default_request: str,
) -> None:
    """A guard: a real value still wins over the default.

    Mutant: drop the stored value and always use the default.
    """
    async with _stored(db_session, key, "https://api.nhtsa.gov/mirror"):
        await getattr(NHTSAService(), method)("1HGCM82633A123456", db_session)

    assert len(requested) == 1
    assert requested[0].startswith("https://api.nhtsa.gov/mirror"), requested[0]


@pytest.mark.parametrize(("method", "key", "default_request"), FETCHES)
async def test_a_stored_url_off_the_allowlist_still_falls_back_loudly(
    db_session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    requested: list[str],
    method: str,
    key: str,
    default_request: str,
) -> None:
    """A guard: a real URL that fails the SSRF check is still blocked, logged
    as an ERROR and replaced by the default. Only blank went quiet.

    Mutant: remove the except branch (the SSRF error escapes the fetch).
    """
    caplog.set_level(logging.WARNING, logger=LOGGER)
    async with _stored(db_session, key, "https://example.com/recalls"):
        await getattr(NHTSAService(), method)("1HGCM82633A123456", db_session)

    assert len(requested) == 1
    assert requested[0].startswith(default_request), requested[0]
    assert any("SSRF protection blocked" in message for message in _errors(caplog))
