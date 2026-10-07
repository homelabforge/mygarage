"""Country profiles: the data layer behind EU/national behaviour.

A profile is a JSON file in ``app/data/country_profiles/<CC>.json`` describing
what differs from one country to the next: the name and cadence of the
periodic technical inspection, the pump labels for fuel, the tax types, the
low-emission-zone scheme, the insurance vocabulary, the open-data sources and
the markers that identify a registration certificate. EU law harmonises a lot
of this, so every member state ``extends`` the ``EU`` baseline and only
restates the sections that differ.

Proper names (« Contrôle technique », « Kfz-Steuer », « Crit'Air ») live here
on purpose: they are the same in every UI language, like a brand. Generic
labels (« Technical inspection ») live in the i18n bundles.

The shape is strict (``extra="forbid"``) so a typo in a data file fails the
profile test rather than silently doing nothing.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.constants.fuel import FUEL_GRADE_VALUES, FUEL_TYPE_VALUES
from app.schemas.vehicle import VehicleType

#: EN 16942 pump labels, the vocabulary of ``fuel_records.fuel_grade``.
EN16942_GRADES: tuple[str, ...] = FUEL_GRADE_VALUES

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileSource(_Strict):
    """Where a figure in the profile comes from, so a reviewer can check it."""

    title: str
    url: str
    retrieved: date


class InspectionStep(_Strict):
    """One step of a roadworthiness cadence.

    The first step says when the first inspection is due (``first_after_years``
    after first registration); every later step says how often it recurs
    (``every_years``) and, optionally, until what vehicle age that rhythm
    applies (``until_age_years``, exclusive). The next due date is the
    previous one plus ``every_years`` of the first step whose ``until_age_years``
    is null or above the vehicle's age at the previous due date.
    """

    # Ranges are checked in the validator below rather than with ge/le: this
    # model is part of the profile response, and the response contract test
    # refuses numeric bounds on anything a response inherits.
    first_after_years: int | None = None
    every_years: int | None = None
    until_age_years: int | None = None

    @model_validator(mode="after")
    def one_kind(self) -> InspectionStep:
        if (self.first_after_years is None) == (self.every_years is None):
            raise ValueError("a step is either first_after_years or every_years")
        if self.first_after_years is not None and self.until_age_years is not None:
            raise ValueError("until_age_years only applies to an every_years step")
        for name, value, upper in (
            ("first_after_years", self.first_after_years, 20),
            ("every_years", self.every_years, 20),
            ("until_age_years", self.until_age_years, 60),
        ):
            if value is not None and not 1 <= value <= upper:
                raise ValueError(f"{name} must be between 1 and {upper}")
        return self


class InspectionSchedule(_Strict):
    """A cadence and the vehicles it applies to."""

    vehicle_types: list[VehicleType] = Field(..., min_length=1)
    #: ``FuelTypeEnum`` values; empty means any fuel.
    fuel_types: list[str] = Field(default_factory=list)
    steps: list[InspectionStep] = Field(..., min_length=2)
    #: A caveat shown next to the computed date (regional rules, exemptions).
    note: str | None = None

    @field_validator("fuel_types")
    @classmethod
    def known_fuels(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in FUEL_TYPE_VALUES]
        if unknown:
            raise ValueError(f"unknown fuel types: {unknown}")
        return v

    @model_validator(mode="after")
    def first_then_every(self) -> InspectionSchedule:
        if self.steps[0].first_after_years is None:
            raise ValueError("the first step must be a first_after_years step")
        if any(s.every_years is None for s in self.steps[1:]):
            raise ValueError("every step after the first must be an every_years step")
        if self.steps[-1].until_age_years is not None:
            raise ValueError("the last step must apply without an age limit")
        return self


class InspectionRules(_Strict):
    name: str
    #: Months before the deadline from which the inspection may be done (FR: 6).
    lead_window_months: int = 0
    #: Months allowed for a re-test after a failed inspection (FR: 2).
    retest_window_months: int | None = None
    schedules: list[InspectionSchedule] = Field(..., min_length=1)

    @model_validator(mode="after")
    def sane_windows(self) -> InspectionRules:
        if not 0 <= self.lead_window_months <= 12:
            raise ValueError("lead_window_months must be between 0 and 12")
        if self.retest_window_months is not None and not 1 <= self.retest_window_months <= 12:
            raise ValueError("retest_window_months must be between 1 and 12")
        return self


class FuelGradePreset(_Strict):
    """A pump name as drivers know it, mapped to its EN 16942 label."""

    id: str = Field(..., pattern=r"^[a-z0-9_]+$")
    label: str
    grade: str
    octane: int | None = None
    fuel_type: str

    @field_validator("grade")
    @classmethod
    def known_grade(cls, v: str) -> str:
        if v not in EN16942_GRADES:
            raise ValueError(f"unknown EN 16942 grade: {v}")
        return v

    @field_validator("octane")
    @classmethod
    def octane_range(cls, v: int | None) -> int | None:
        # The fuel record's own octane rule (50-150, AKI or RON).
        if v is not None and not 50 <= v <= 150:
            raise ValueError("octane must be between 50 and 150")
        return v

    @field_validator("fuel_type")
    @classmethod
    def known_fuel(cls, v: str) -> str:
        if v not in FUEL_TYPE_VALUES:
            raise ValueError(f"unknown fuel type: {v}")
        return v


class FuelRules(_Strict):
    octane_scale: Literal["RON", "AKI"] = "AKI"
    #: US pumps sell clear and dyed (off-road) diesel; most of Europe does not.
    diesel_dyed_distinction: bool = True
    grades: list[FuelGradePreset] = Field(default_factory=list)


class TaxRules(_Strict):
    #: Tax type codes in the order the form should offer them.
    types: list[str] = Field(default_factory=list)
    #: National proper name per code (« Malus écologique »), never translated.
    names: dict[str, str] = Field(default_factory=dict)


LezScheme = Literal["critair", "umweltplakette", "lez_registration", "ztl", "dgt_label"]


class LezRules(_Strict):
    scheme: LezScheme | None = None
    name: str | None = None
    url: str | None = None


class NoClaimsScheme(_Strict):
    scheme: Literal["crm", "sf_klasse", "classe_di_merito", "bonus_malus"]
    name: str
    #: Regex the frontend uses as a hint for the field; the API stays lenient.
    pattern: str
    example: str


class InsuranceRules(_Strict):
    policy_types: list[str] = Field(default_factory=list)
    coverage_keys: list[str] = Field(default_factory=list)
    no_claims: NoClaimsScheme | None = None


class TollRules(_Strict):
    #: Brand names, for reference; ``frontend/src/constants/tollSystems.ts``
    #: stays the list the toll form offers.
    systems: list[str] = Field(default_factory=list)


class DataSources(_Strict):
    #: Recall provider ids (``nhtsa``, ``rappelconso``); empty means none.
    recalls: list[str] = Field(default_factory=list)
    #: Fuel price provider id, or null.
    fuel_prices: str | None = None


class RegistrationCertificateRules(_Strict):
    #: Uppercase phrases that identify this country's certificate.
    markers: list[str] = Field(default_factory=list)
    #: Regexes for the licence plate formats.
    plate_patterns: list[str] = Field(default_factory=list)
    #: Field P.3 codes → ``FuelTypeEnum`` value.
    energy_codes: dict[str, str] = Field(default_factory=dict)
    #: Field J.1 national categories (FR: VP, CTTE, MTL…).
    national_categories: list[str] = Field(default_factory=list)

    @field_validator("energy_codes")
    @classmethod
    def known_fuels(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = sorted({f for f in v.values() if f not in FUEL_TYPE_VALUES})
        if unknown:
            raise ValueError(f"unknown fuel types in energy_codes: {unknown}")
        return v

    @field_validator("plate_patterns")
    @classmethod
    def compilable(cls, v: list[str]) -> list[str]:
        for pattern in v:
            re.compile(pattern)
        return v


class CountryProfile(_Strict):
    """A country's profile after ``extends`` has been resolved."""

    country: str
    extends: str | None = None
    #: Proper names keyed by topic (``inspection``, ``registration_certificate``…).
    names: dict[str, str] = Field(default_factory=dict)
    currency: str | None = Field(None, min_length=3, max_length=3)
    inspection: InspectionRules | None = None
    fuel: FuelRules = Field(default_factory=FuelRules)
    taxes: TaxRules = Field(default_factory=TaxRules)
    lez: LezRules = Field(default_factory=LezRules)
    insurance: InsuranceRules = Field(default_factory=InsuranceRules)
    tolls: TollRules = Field(default_factory=TollRules)
    default_reminder_packs: list[str] = Field(default_factory=list)
    data_sources: DataSources = Field(default_factory=DataSources)
    registration_certificate: RegistrationCertificateRules = Field(
        default_factory=RegistrationCertificateRules
    )
    sources: list[ProfileSource] = Field(default_factory=list)

    @field_validator("country", "extends")
    @classmethod
    def two_letters(cls, v: str | None) -> str | None:
        if v is not None and not _COUNTRY_RE.match(v):
            raise ValueError("a profile id is two uppercase letters")
        return v


class CountryProfileSummary(BaseModel):
    """What the list endpoint returns: enough to build a picker."""

    country: str
    names: dict[str, str]
    has_inspection: bool
    lez_scheme: str | None
    octane_scale: str
