"""How one policy's premium divides among the vehicles it covers.

Every figure here is in the policy's own unit: the amount per
`premium_frequency` period. Nothing in this module knows about dates; turning
a per-period share into a cost over a window is `insurance_cost`'s job.

A link's `premium_share` is either EXPLICIT (the user, the importer or the
migration said what this vehicle costs) or unset, in which case the vehicle
takes an even split of whatever the explicit shares leave.
"""

from collections.abc import Hashable, Sequence
from decimal import ROUND_DOWN, Decimal

CENT = Decimal("0.01")


class AllocationError(ValueError):
    """The shares cannot belong to a policy with this total."""


def effective_shares(
    total: Decimal | None, shares: Sequence[tuple[Hashable, Decimal | None]]
) -> dict[Hashable, Decimal | None]:
    """Each link's effective per-period share, keyed as given.

    `shares` is `(key, explicit_share_or_None)` in link-id order. An unset
    share is `(total - explicit) / unset_count`, rounded DOWN to the cent, and
    the cents that rounding leaves over go one each to the earliest unset
    links, so the effective shares always sum to the total exactly. With no
    total there is nothing to split: unset shares stay None.
    """
    result: dict[Hashable, Decimal | None] = {}
    unset = [key for key, share in shares if share is None]
    for key, share in shares:
        if share is not None:
            result[key] = share
    if not unset:
        return result
    if total is None:
        for key in unset:
            result[key] = None
        return result

    explicit = sum((share for _, share in shares if share is not None), Decimal("0"))
    remainder = max(total - explicit, Decimal("0"))
    each = (remainder / len(unset)).quantize(CENT, rounding=ROUND_DOWN)
    leftover_cents = int((remainder - each * len(unset)) / CENT)
    for index, key in enumerate(unset):
        result[key] = each + (CENT if index < leftover_cents else Decimal("0"))
    return result


def validate_allocation(total: Decimal | None, shares: Sequence[Decimal | None]) -> None:
    """Raise `AllocationError` when the shares cannot belong to this total.

    With every share explicit they must sum to the total EXACTLY: a renewal
    from 600 to 700 that kept 300 + 300 would silently leave 100 that no
    vehicle, export or chart accounts for. With some unset, the explicit ones
    only must not exceed it. A NULL total is an unknown premium, and an unknown
    cannot be contradicted.
    """
    if total is None or not shares:
        return
    explicit = [share for share in shares if share is not None]
    allocated = sum(explicit, Decimal("0"))
    if len(explicit) == len(shares):
        if allocated != total:
            raise AllocationError(
                f"The vehicle shares add up to {allocated}, but the policy premium is "
                f"{total}. Adjust the shares or let them split evenly."
            )
    elif allocated > total:
        raise AllocationError(
            f"The vehicle shares add up to {allocated}, more than the policy premium of {total}."
        )


def rescale_shares(
    shares: Sequence[tuple[Hashable, Decimal | None]],
    old_total: Decimal | None,
    new_total: Decimal | None,
) -> dict[Hashable, Decimal | None]:
    """Carry explicit shares to a new total as PROPORTIONS.

    Unset shares stay unset. When there is no usable old total to take a
    proportion of (NULL or zero), or no new total, every share resets to unset,
    which is an even split. The cents lost to rounding go to the earliest
    explicit links so a fully explicit allocation still sums exactly.
    """
    if not old_total or new_total is None:
        return {key: None for key, _ in shares}

    result: dict[Hashable, Decimal | None] = {}
    explicit_keys: list[Hashable] = []
    for key, share in shares:
        if share is None:
            result[key] = None
            continue
        result[key] = (share * new_total / old_total).quantize(CENT, rounding=ROUND_DOWN)
        explicit_keys.append(key)

    if explicit_keys and len(explicit_keys) == len(shares):
        scaled = sum((result[key] for key in explicit_keys), Decimal("0"))  # type: ignore[misc]
        leftover_cents = int((new_total - scaled) / CENT)
        for index, key in enumerate(explicit_keys):
            if index < leftover_cents:
                result[key] = result[key] + CENT  # type: ignore[operator]
    return result
