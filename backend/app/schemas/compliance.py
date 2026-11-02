"""What a vehicle's country asks of it: the low-emission-zone class, the next
periodic inspection, the Euro class, with the figures behind them (#211)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.country_profile import LezScheme, ProfileSource
from app.schemas.maintenance import LenientAnchorKind
from app.utils.lez import LezBasis


class LezStatus(BaseModel):
    """The country's low-emission scheme and the class this vehicle has in it."""

    scheme: LezScheme
    #: The scheme's proper name (« Crit'Air »), never translated.
    name: str | None = None
    url: str | None = None
    #: The class: Crit'Air « 0 » to « 5 », or whatever the person set by hand.
    #: Null when the scheme is not computed here or the vehicle is unclassified.
    value: str | None = None
    #: What the value rests on. 'override': set on the vehicle; 'euro_class':
    #: the recorded Euro class; 'first_registration': a Euro class estimated
    #: from the first registration date; 'fuel': the fuel alone decides.
    basis: LezBasis | None = None
    overridden: bool = False
    #: Whether this scheme's class is computed by MyGarage at all (Crit'Air
    #: is; the others only show a class set by hand).
    computed: bool = False


class InspectionStatus(BaseModel):
    """The periodic inspection as the automatic engine (#211) tracks it."""

    #: The test's proper name in the country (« Contrôle technique », « HU »).
    name: str
    #: Whether the engine keeps the reminder (its rule exists and is active).
    automatic: bool
    next_due_date: date | None = None
    lead_days: int | None = None
    #: The first day the test may be done, when the country has a window.
    window_opens_on: date | None = None
    reminder_id: int | None = None
    rule_id: int | None = None
    anchor_kind: LenientAnchorKind = None
    #: The due date was computed from the registration date, not from a test
    #: on record.
    from_registration: bool = False


class ComplianceResponse(BaseModel):
    vin: str
    #: The country whose rules apply (vehicle → owner → instance), or null.
    country: str | None = None
    #: The profile that answered: the country's own, or « EU » for a member
    #: state without a file. Null without a profile.
    profile_country: str | None = None
    euro_class: int | None = None
    #: The Euro class above was estimated from the first registration date.
    euro_class_estimated: bool = False
    lez: LezStatus | None = None
    inspection: InspectionStatus | None = None
    sources: list[ProfileSource] = Field(default_factory=list)
    #: Why nothing is computed, when nothing is.
    reason: Literal["no_country", "no_profile"] | None = None
