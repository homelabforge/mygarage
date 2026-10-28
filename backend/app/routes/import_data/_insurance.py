"""Insurance rows: coverages, bounds and the policy write both importers share."""

# pyright: reportPrivateUsage=false, reportUnusedFunction=false, reportUnusedClass=false

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    InsuranceCoverage,
    InsurancePolicy,
    InsurancePolicyField,
    InsurancePolicyVehicle,
)
from app.models.vehicle import Vehicle
from app.routes.import_data._common import _ImportBoundError, _InsuranceRowError, _within_api_bounds
from app.schemas._money import MONEY_MAX
from app.schemas.insurance import CoverageEntry, PolicyVehicleCreate
from app.utils.insurance_coverages import (
    COVERAGE_BY_KEY,
    coverage_row,
    parse_coverage_lines,
    place_leftovers,
)
from app.utils.logging_utils import sanitize_for_log
from app.utils.money_fits import too_large

logger = logging.getLogger(__name__)


def _whole_cents(value: Decimal | None, column: str) -> Decimal | None:
    """The amount, or a row error when it has a fraction of a cent."""
    if value is None:
        return None
    if value != value.quantize(Decimal("0.01")):
        raise _InsuranceRowError(f"{column} must be a whole number of cents")
    if value < 0:
        raise _InsuranceRowError(f"{column} must not be negative")
    return value


def _whole_count(value: Decimal, column: str) -> Decimal:
    """A count slot's value, or a row error when it has a fraction.

    A count is a number of days, not money, so the whole-cents rule lets 30.5
    through. The flat exports write a count with no decimals, which turns a
    stored 30.5 into 30 the next time the policy is exported.
    """
    if value != value.to_integral_value():
        raise _InsuranceRowError(f"{column} must be a whole number")
    return value


def _coverages_from_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The standard coverages of a schema-8 backup entry.

    Importers build ORM rows directly, so the API schema's rules do not reach
    them and are re-applied here from the same catalogue: a slot the catalogue
    does not give a coverage is an error rather than a silently dropped amount,
    every money figure is a whole number of cents, and a count is whole.
    """
    rows = []
    for item in raw:
        key = item.get("coverage_key")
        coverage = COVERAGE_BY_KEY.get(key)
        if coverage is None:
            logger.warning("Import: unknown insurance coverage %s, skipped", sanitize_for_log(key))
            continue
        slots = dict(coverage.slots())
        values = {}
        for name in ("limit_primary", "limit_secondary", "deductible", "premium"):
            value = item.get(name)
            value = Decimal(str(value)) if value is not None else None
            slot = slots.get(name)
            column = f"{coverage.label} {name}"
            if value is not None and slot is None:
                raise _InsuranceRowError(f"{key} has no {name}")
            if value is not None and slot is not None and slot.kind == "count":
                value = _whole_count(value, column)
            values[name] = _whole_cents(value, column)
        rows.append({"coverage_key": key, **values})
    return rows


def _coverages_from_text(text: str | None) -> tuple[list[dict[str, Any]], list[dict], list[str]]:
    """A free-text coverage box as coverages, named fields and leftover prose.

    The CSV column and a schema-7 backup both carry one text box, read here
    through the SAME parser migration 108 uses AND placed the same way, so a
    restored old backup lands exactly what an in-place upgrade would have
    produced rather than only its coverage rows.
    """
    parse = parse_coverage_lines(text)
    leftover_fields, kept_prose = place_leftovers(parse)
    fields = [{"label": label, "value": value} for label, value in leftover_fields]
    return [coverage_row(item) for item in parse.coverages], fields, kept_prose


def _merge_converted(row: dict[str, Any], text: str | None) -> None:
    """Fold a text box's conversion into a row that may already carry its own
    named fields and notes; nothing the box held is dropped."""
    coverages, fields, notes = _coverages_from_text(text)
    row["coverages"] = coverages
    row["fields"] = [*(row.get("fields") or []), *fields]
    if notes:
        row["notes"] = "\n".join(filter(None, [(row.get("notes") or "").rstrip(), *notes])) or None


def _insurance_amounts_within_api_bounds(row: dict[str, Any]) -> None:
    """Hold a row's share, deductible and coverage amounts to the API's bounds.

    Importers build ORM rows directly, so the Create schemas never ran on them,
    and a number past its column was a 500 on PostgreSQL.
    """
    _within_api_bounds(
        PolicyVehicleCreate, premium_share=row["premium"], deductible=row["deductible"]
    )
    coverages: list[dict[str, Any]] = row.get("coverages") or []
    for coverage in coverages:
        try:
            _within_api_bounds(
                CoverageEntry,
                limit_primary=coverage.get("limit_primary"),
                limit_secondary=coverage.get("limit_secondary"),
                deductible=coverage.get("deductible"),
                premium=coverage.get("premium"),
            )
        except _ImportBoundError as e:
            raise _ImportBoundError(f"{coverage.get('coverage_key')} {e.reason}") from e


def _grown_premium(total: Decimal, premium: Decimal) -> Decimal:
    """A policy's premium plus one more vehicle's. Each fits, the sum may not."""
    grown = total + premium
    if grown > MONEY_MAX:
        raise _ImportBoundError(too_large("The policy premium"))
    return grown


async def _import_insurance_row(
    db: AsyncSession,
    access: Any,
    vin: str,
    row: dict[str, Any],
    skip_duplicates: bool,
) -> bool:
    """Put one vehicle's insurance row onto a household policy.

    Returns False when the row was skipped as a duplicate. The policy is found
    by the same key migration 107 merges on, so importing two vehicles' files
    rebuilds ONE household policy.

    THE IMPORTER NEVER REWRITES EXISTING MONEY. A PRE-EXISTING policy only
    ever grows by the imported vehicle's own premium, which by construction
    leaves every existing effective share unchanged. An unknown (blank) premium
    is never attached to a priced pre-existing policy, because an unset share
    would dilute every sibling; it gets a policy of its own.
    """
    provider = (row["provider"] or "").strip()
    number = (row["policy_number"] or "").strip()
    # Importers build ORM rows directly, so the API schema's whole-cents rule
    # does not reach them: 0.005 + 0.005 adds up to a 0.01 premium here and is
    # then STORED as two 0.01 shares, which no longer fit it.
    premium: Decimal | None = _whole_cents(row["premium"], "Premium")
    row["deductible"] = _whole_cents(row["deductible"], "Deductible")
    _insurance_amounts_within_api_bounds(row)
    frequency = row["premium_frequency"]

    candidates = (
        (
            await db.execute(
                select(InsurancePolicy)
                .where(
                    func.lower(func.trim(InsurancePolicy.provider)) == provider.lower(),
                    func.trim(InsurancePolicy.policy_number) == number,
                    InsurancePolicy.start_date == row["start_date"],
                    InsurancePolicy.end_date == row["end_date"],
                    InsurancePolicy.premium_frequency.is_(None)
                    if frequency is None
                    else InsurancePolicy.premium_frequency == frequency,
                )
                .order_by(InsurancePolicy.id)
                # Two imports for DIFFERENT vehicles hold different vehicle locks
                # on PostgreSQL yet can target the same policy, and both add to
                # its premium: lock the policy rows before reading their money.
                # (SQLite imports already hold the database write lock, and
                # `with_for_update` compiles away there.)
                .with_for_update(of=InsurancePolicy)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    # THE OWNER BOUNDARY, same as migration 107's merge key: a row joins a
    # policy only when every vehicle already on it belongs to this vehicle's
    # owner (an empty policy counts by its creator). Without it an admin
    # importing two owners' look-alike files would weld them into one policy,
    # and each owner would gain a window into, and a say over, the other's.
    owner_id = await db.scalar(select(Vehicle.user_id).where(Vehicle.vin == vin))
    linked_vins = {link.vin for p in candidates for link in p.vehicle_links}
    owners = (
        dict(
            (
                await db.execute(
                    select(Vehicle.vin, Vehicle.user_id).where(Vehicle.vin.in_(linked_vins))
                )
            ).all()
        )
        if linked_vins
        else {}
    )

    def _same_owner(policy: InsurancePolicy) -> bool:
        if not policy.vehicle_links:
            return policy.created_by_user_id == owner_id
        return all(owners.get(link.vin) == owner_id for link in policy.vehicle_links)

    readable = [p for p in candidates if access.can_read(p) and _same_owner(p)]
    if skip_duplicates and any(link.vin == vin for p in readable for link in p.vehicle_links):
        return False

    target: InsurancePolicy | None = None
    for policy in readable:
        if any(link.vin == vin for link in policy.vehicle_links):
            continue
        if premium is None and policy.premium_amount is not None:
            continue
        if not access.can_write(policy):
            raise _InsuranceRowError(
                "this policy already exists and adding a vehicle to it needs write "
                "access to every vehicle it covers"
            )
        target = policy
        break

    # Children are appended while a new policy is still PENDING: once flushed,
    # touching its unloaded collections would be an async lazy load.
    async with db.begin_nested():
        if target is None:
            target = InsurancePolicy(
                provider=provider,
                policy_number=number,
                start_date=row["start_date"],
                end_date=row["end_date"],
                premium_amount=premium,
                premium_frequency=frequency,
                notes=row.get("policy_notes"),
                created_by_user_id=access.user_id,
            )
            db.add(target)
            for order, item in enumerate(row.get("policy_fields") or []):
                target.all_fields.append(
                    InsurancePolicyField(label=item["label"], value=item["value"], sort_order=order)
                )
        elif target.premium_amount is not None and premium is not None:
            target.premium_amount = _grown_premium(target.premium_amount, premium)

        link = InsurancePolicyVehicle(
            vin=vin,
            policy_type=row["policy_type"],
            premium_share=premium,
            deductible=row["deductible"],
            notes=row["notes"],
            effective_to=row.get("effective_to"),
        )
        target.vehicle_links.append(link)
        for coverage in row.get("coverages") or []:
            link.coverages.append(InsuranceCoverage(**coverage))
        for order, item in enumerate(row.get("fields") or []):
            target.all_fields.append(
                InsurancePolicyField(
                    policy_vehicle=link, label=item["label"], value=item["value"], sort_order=order
                )
            )
        await db.flush()
    return True
