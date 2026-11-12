"""Formatting-layer context: whose unit preferences apply to a render.

R4 (revised): conversion (`unit_adapters.py`, `unit_counterparts.py`) and
formatting (`unit_formatting.py`, this module) are separate layers.
`RenderContext` is the formatting layer's one input describing *whose*
preferences a call site should render with; `unit_formatting.py`'s functions
consume it to turn a canonical `Decimal` into a human-readable string.

Three resolution paths exist, and they are deliberately not interchangeable:

- A **request** (`render_context_for_request`) uses the caller's own resolved
  unit set, never the vehicle owner's. `get_vehicle_or_403` admits admins and
  shared users whose preferences differ from the owner's, and a shared viewer
  reading a PDF should see their own units, not the owner's.
- A **scheduled job** (`render_context_for_vehicle`) has no caller, so it
  uses the vehicle owner's render context, falling back to the instance
  default when the vehicle is ownerless (`Vehicle.user_id IS NULL` is a real,
  reachable state, not a defensive-only branch: see the archived-vehicles
  query at `routes/vehicles.py:718`) or does not exist.
- **`auth_mode=none`** (`render_context_default`) uses the instance default:
  there is no user row to resolve from, and `show_both` is always `False`
  for it, since there is no user who could have opted in.

`render_context_for_user` is NOT a fourth path and is not a call site's entry
point: it is the shared, synchronous body the two user-bearing paths above
delegate to once they have a `User` in hand, and it has no caller in `app/`
outside this module. It stays public because both those paths are one line
of it and the split is what keeps them from re-deriving `show_both`
independently.

No new query, header, or body parameter is introduced anywhere in this
module: every path resolves from data callers already have (the current
user, a VIN, or nothing at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.units import UnitSet
from app.models.user import User
from app.models.vehicle import Vehicle
from app.utils.default_unit_prefs import load_default_unit_prefs
from app.utils.unit_resolution import UnitPreferenceShape, apply_vehicle_units, resolve_units


@dataclass(frozen=True)
class RenderContext:
    """Whose units, and whether to show the counterpart, for one render."""

    units: UnitSet
    show_both: bool


class UserRenderContextShape(UnitPreferenceShape, Protocol):
    """`UnitPreferenceShape` plus the one extra field `render_context_for_user`
    needs: whether this user opted into showing the counterpart alongside
    their primary unit.

    A Protocol rather than the ORM `User`, for the same reason
    `UnitPreferenceShape` itself is one (see its docstring in
    `unit_resolution.py`). `User` reaches it through the
    `UserRenderContextSource` union below.
    """

    @property
    def show_both_units(self) -> bool: ...


class VehicleUnitShape(Protocol):
    """What the vehicle half of a render needs: its VIN and odometer unit.

    Anything carrying the two attributes fits; the ORM `Vehicle` reaches it
    through the `VehicleUnitSource` union below.
    """

    @property
    def vin(self) -> str: ...
    @property
    def distance_unit(self) -> str | None: ...


# Pyright never applies a descriptor's __get__ when it matches a protocol, so an
# ORM model fails a protocol on its Mapped columns. The model goes in the union
# by name; the alias is only ever read by pyright.
type UserRenderContextSource = User | UserRenderContextShape
type VehicleUnitSource = Vehicle | VehicleUnitShape


def with_vehicle(ctx: RenderContext, vehicle: VehicleUnitSource) -> RenderContext:
    """`ctx` with the vehicle's odometer unit, and the speed that goes with it,
    laid on top (#172). Everything else, show-both included, is unchanged, and
    an Account-default vehicle returns `ctx` itself."""
    units = apply_vehicle_units(ctx.units, vehicle.distance_unit, vin=vehicle.vin)
    if units is ctx.units:
        return ctx
    return RenderContext(units=units, show_both=ctx.show_both)


def render_context_for_user(user: UserRenderContextSource) -> RenderContext:
    """The render context for a known `User`, whoever resolved them.

    The shared body of `render_context_for_request` (the caller) and
    `render_context_for_vehicle` (the owner), not an entry point of its own:
    nothing in `app/` outside this module calls it, and a new request-driven
    surface wants `render_context_for_request`, which owns the "instance
    default when there is no caller" half of the policy.

    Synchronous and pure, like `resolve_units`: it reads only what `user`
    already carries.
    """
    return RenderContext(units=resolve_units(user), show_both=user.show_both_units)


async def render_context_default(db: AsyncSession) -> RenderContext:
    """The instance-wide default render context.

    Used directly for `auth_mode=none` clients, and as the fallback for a
    scheduled job whose vehicle has no owner or does not exist.
    `show_both` is always `False`: there is no user to have opted into it.
    """
    units = await load_default_unit_prefs(db)
    return RenderContext(units=units, show_both=False)


async def render_context_for_request(
    user: UserRenderContextSource | None,
    db: AsyncSession,
    vehicle: VehicleUnitSource | None = None,
) -> RenderContext:
    """The render context for an HTTP request made by `user`.

    The single entry point every request-driven surface should use, so the
    "caller's units, instance default when there is no caller" policy lives
    in one place instead of being re-derived at each route. `user` is `None`
    only on an ``auth_mode=none`` instance, where `require_auth` returns
    `None` and there is no user row to resolve from.

    Deliberately the CALLER's units, never the vehicle owner's:
    `get_vehicle_or_403` admits admins and users a vehicle is shared with,
    whose preferences differ from the owner's, and a shared viewer reading a
    report should see their own units. A scheduled job has no caller and
    uses `render_context_for_vehicle` instead.

    With `vehicle`, the result also carries that vehicle's odometer unit
    (#172). That is a fact about the vehicle, not the owner's preference, so it
    applies to every caller alike and "the caller's units" above still holds
    for everything else.
    """
    base = await render_context_default(db) if user is None else render_context_for_user(user)
    return base if vehicle is None else with_vehicle(base, vehicle)


async def render_context_for_vehicle_row(
    db: AsyncSession,
    vehicle: VehicleUnitSource,
    owner: UserRenderContextSource | None,
) -> RenderContext:
    """`render_context_for_vehicle` for a caller that already holds the row.

    Takes the owner explicitly and never reads a relationship: `Vehicle.user`
    is lazy, and touching it inside an AsyncSession raises MissingGreenlet,
    which a scheduled loop's per-vehicle `except` would swallow silently.
    """
    base = await render_context_default(db) if owner is None else render_context_for_user(owner)
    return with_vehicle(base, vehicle)


async def render_context_for_vehicle(db: AsyncSession, vin: str) -> RenderContext:
    """The render context a scheduled job should use for the vehicle at `vin`.

    Resolves to the vehicle's owner's render context. Falls back to the
    instance default (`render_context_default`) when the vehicle has no
    owner (`user_id IS NULL`) or the VIN does not exist at all -- both are
    reachable in production (an ownerless vehicle from a since-disabled
    `auth_mode=none` window; a stale or mistyped VIN passed in from a job
    queue), so this falls back rather than raising either way.

    Either way the vehicle's own odometer unit is laid on top (#172).
    """
    row = (
        await db.execute(
            select(Vehicle, User)
            .outerjoin(User, Vehicle.user_id == User.id)
            .where(Vehicle.vin == vin)
        )
    ).first()
    if row is None:
        return await render_context_default(db)
    vehicle, owner = row
    return await render_context_for_vehicle_row(db, vehicle, owner)
