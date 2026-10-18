"""Setting a reading's alert lines: PUT /api/livelink/parameters/{key}.

The tank settings save a tank's low and critical lines here, and a blank field
switches that line off, so an explicit null clears where an omitted field is
left alone.
"""

import math

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

_PREFIX = "PARAMLINE_"
PCT = f"{_PREFIX}LEVEL"
TEMP = f"{_PREFIX}TEMP"
# Torque's volumetric efficiency: a percent with no class, which runs past 100.
VE = f"{_PREFIX}KFF1269"


@pytest_asyncio.fixture(autouse=True)
async def _params(db_session):
    from app.models.livelink_parameter import LiveLinkParameter

    async def _wipe():
        await db_session.execute(
            delete(LiveLinkParameter).where(LiveLinkParameter.param_key.like(f"{_PREFIX}%"))
        )
        await db_session.commit()

    await _wipe()
    db_session.add(
        LiveLinkParameter(
            param_key=PCT,
            unit="%",
            # The tank's level, as the Mopeka preset registers it.
            param_class="propane",
            warning_min=25.0,
            critical_min=10.0,
            show_on_dashboard=True,
            archive_only=False,
        )
    )
    db_session.add(
        LiveLinkParameter(param_key=TEMP, unit="C", show_on_dashboard=True, archive_only=False)
    )
    db_session.add(
        LiveLinkParameter(param_key=VE, unit="%", show_on_dashboard=True, archive_only=False)
    )
    await db_session.commit()
    yield
    await _wipe()


async def _put(client, headers, key, body):
    return await client.put(f"/api/livelink/parameters/{key}", json=body, headers=headers)


async def _lines(db_session, key) -> tuple[float | None, float | None, float | None]:
    from app.models.livelink_parameter import LiveLinkParameter

    db_session.expire_all()
    param = (
        await db_session.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key == key)
        )
    ).scalar_one()
    return param.warning_min, param.critical_min, param.warning_max


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sets_both_lines(client, auth_headers, db_session):
    resp = await _put(client, auth_headers, PCT, {"warning_min": 30, "critical_min": 12})

    assert resp.status_code == 200
    assert (resp.json()["warning_min"], resp.json()["critical_min"]) == (30.0, 12.0)
    assert await _lines(db_session, PCT) == (30.0, 12.0, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_null_switches_a_line_off(client, auth_headers, db_session):
    resp = await _put(client, auth_headers, PCT, {"critical_min": None})

    assert resp.status_code == 200
    assert await _lines(db_session, PCT) == (25.0, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_an_omitted_line_is_left_alone(client, auth_headers, db_session):
    resp = await _put(client, auth_headers, PCT, {"show_on_dashboard": False})

    assert resp.status_code == 200
    assert await _lines(db_session, PCT) == (25.0, 10.0, None)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"warning_min": 25, "critical_min": 25},
        {"warning_min": 20, "critical_min": 30},
        # Against the stored low line, 25.
        {"critical_min": 40},
        # Against the stored critical line, 10.
        {"warning_min": 5},
    ],
)
async def test_critical_must_sit_below_low(client, auth_headers, db_session, body):
    resp = await _put(client, auth_headers, PCT, body)

    assert resp.status_code == 422
    assert await _lines(db_session, PCT) == (25.0, 10.0, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_clearing_low_frees_critical(client, auth_headers, db_session):
    resp = await _put(client, auth_headers, PCT, {"warning_min": None, "critical_min": 40})

    assert resp.status_code == 200
    assert await _lines(db_session, PCT) == (None, 40.0, None)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [{"warning_min": 101}, {"critical_min": -1}, {"warning_max": 100.5}],
)
async def test_a_percent_reading_stays_within_0_to_100(client, auth_headers, db_session, body):
    resp = await _put(client, auth_headers, PCT, body)

    assert resp.status_code == 422
    assert await _lines(db_session, PCT) == (25.0, 10.0, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_the_ends_of_the_percent_scale_are_allowed(client, auth_headers, db_session):
    resp = await _put(client, auth_headers, PCT, {"warning_min": 100, "critical_min": 0})

    assert resp.status_code == 200
    assert await _lines(db_session, PCT) == (100.0, 0.0, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_a_percent_that_is_not_a_fill_level_can_leave_0_to_100(
    client, auth_headers, db_session
):
    """Volumetric efficiency passes 100 and a fuel trim goes below 0 (TQ-L3).

    Only fill-like classes keep the bound; an unclassified percent is free.
    """
    resp = await _put(client, auth_headers, VE, {"warning_min": -5, "warning_max": 120})

    assert resp.status_code == 200, resp.text
    assert await _lines(db_session, VE) == (-5.0, None, 120.0)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("param_class", ["percentage", "power_factor", "battery"])
async def test_every_fill_like_class_keeps_the_bound(
    client, auth_headers, db_session, param_class
):
    """The tank's `propane` is covered above; these are the other bounded classes."""
    from app.models.livelink_parameter import LiveLinkParameter

    param = (
        await db_session.execute(
            select(LiveLinkParameter).where(LiveLinkParameter.param_key == VE)
        )
    ).scalar_one()
    param.param_class = param_class
    await db_session.commit()

    resp = await _put(client, auth_headers, VE, {"warning_max": 120})

    assert resp.status_code == 422, resp.text
    assert await _lines(db_session, VE) == (None, None, None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_other_units_are_not_held_to_percent(client, auth_headers, db_session):
    """A WiCAN coolant line is in its own unit, below zero if it likes."""
    resp = await _put(client, auth_headers, TEMP, {"warning_min": -40, "warning_max": 120})

    assert resp.status_code == 200
    assert await _lines(db_session, TEMP) == (-40.0, None, 120.0)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["warning_min", "critical_min", "warning_max"])
async def test_a_line_must_be_a_number(client, auth_headers, db_session, field):
    """NaN compares false both ways, so it would be a line nothing ever crosses."""
    resp = await client.put(
        f"/api/livelink/parameters/{TEMP}",
        content=f'{{"{field}": NaN}}',
        headers={**auth_headers, "Content-Type": "application/json"},
    )

    assert resp.status_code == 422
    assert resp.json()["details"][0]["input"] == "nan"
    lines = await _lines(db_session, TEMP)
    assert not any(line is not None and math.isnan(line) for line in lines)
