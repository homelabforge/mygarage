"""EU registration certificate parser (Directive 1999/37/EC) (#211).

Every member state prints the same harmonised field codes on its
certificate: A plate, B first registration, C.1 holder, D.1 make, D.2
type/variant/version, D.3 commercial name, E VIN, F.1 maximum laden mass,
G mass in service, J EU category, J.1 national category, K type approval,
P.1 displacement, P.2 power in kW, P.3 energy code, P.6 fiscal power, S.1
seats, V.7 CO₂, V.9 Euro class, X.1 last inspection, Y.1 to Y.6 taxes.

Two ways in, one ``RegistrationData`` out:

- ``EURegistrationCertificateParser.parse(text)`` reads the TEXT of a PDF
  with a text layer (the ANTS provisional certificate, a scan that was
  OCR'd elsewhere): codes are repaired (``D 1``, ``D1``, ``D-1`` → ``D.1``),
  each code's value is what follows it on the line (or the next line), and
  strong shapes (a 17-character VIN, a plate matching a country's pattern,
  a date, a P.3 code) are checked before a value is believed.
- ``from_llm_fields(fields)`` takes the JSON a vision model returned for a
  photo (see ``document_prompts.registration_certificate``) through the
  SAME validators, so a model's guess is held to the same shape as a
  regex match: an invalid VIN or an unparseable date is dropped with a
  warning, never applied.

The country is the certificate's own marker (« CERTIFICAT
D'IMMATRICULATION », « ZULASSUNGSBESCHEINIGUNG »), else the plate's format,
else unknown.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.constants.countries import is_country_code
from app.constants.fuel import CARTE_GRISE_ENERGY_CODES
from app.services.country_profile_service import available_profile_ids, load_profile

from .base import BaseDocumentParser, DocumentData, DocumentType

logger = logging.getLogger(__name__)

#: The harmonised codes the parser captures, and the attribute each fills.
CODE_FIELDS: dict[str, str] = {
    "A": "plate",
    "B": "first_registration",
    "C.1": "holder",
    "D.1": "make",
    "D.2": "type_variant_version",
    "D.3": "commercial_name",
    "E": "vin",
    "F.1": "max_mass_kg",
    "G": "mass_in_service_kg",
    "J": "eu_category",
    "J.1": "national_category",
    "K": "type_approval",
    "P.1": "displacement_cc",
    "P.2": "power_kw",
    "P.3": "energy_code",
    "P.6": "fiscal_power",
    "S.1": "seats",
    "V.7": "co2_g_km",
    "V.9": "euro_class",
    "X.1": "last_inspection",
}
TAX_CODES: tuple[str, ...] = ("Y.1", "Y.2", "Y.3", "Y.4", "Y.5", "Y.6")
#: Every code printed on a certificate, captured or not: a code that is not
#: captured still ends the value of the code before it on the same line.
KNOWN_CODES: frozenset[str] = frozenset(
    list(CODE_FIELDS)
    + list(TAX_CODES)
    + ["C.4", "F.2", "F.3", "I", "J.2", "J.3", "P.5", "Q", "S.2", "U.1", "U.2", "V.8", "Z.1", "Z.2"]
)
#: The JSON keys the vision prompt uses (the dot dropped) → the code.
LLM_KEY_TO_CODE: dict[str, str] = {code.replace(".", ""): code for code in CODE_FIELDS} | {
    code.replace(".", ""): code for code in TAX_CODES
}

#: How much each field weighs in the confidence score (sums past 100; capped).
_WEIGHTS: dict[str, int] = {
    "vin": 30,
    "first_registration": 15,
    "make": 10,
    "commercial_name": 10,
    "energy_code": 10,
    "plate": 10,
    "fiscal_power": 5,
    "co2_g_km": 5,
    "euro_class": 5,
    "last_inspection": 5,
    "country": 5,
}

_VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")
_VIN_ANYWHERE_RE = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")
_DATE_RE = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})|(\d{4})-(\d{2})-(\d{2})")
_EU_CATEGORY_RE = re.compile(r"^[MNLOT]\d{1,2}[A-Z]?E?$")
_INT_RE = re.compile(r"-?\d[\d ]*")
_DECIMAL_RE = re.compile(r"\d[\d .,]*")
_TYPE_APPROVAL_PREFIX_RE = re.compile(r"^([A-Z])\.(\d)")
_GENERIC_PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 -]{1,18}[A-Z0-9]$")
#: ``D 1``, ``D1``, ``D-1`` → ``D.1``, only for letters that have numbered
#: sub-fields on the certificate; the lookarounds keep ``VF1`` in a VIN and
#: ``M1`` in a category whole.
_CODE_REPAIR_RE = re.compile(r"(?<![A-Z0-9])([CDFJPSUVXYZ])\s*[.\-]?\s*([1-9])(?![0-9A-Z])")
#: A code token standing on its own: not inside a word (« Euro » is not the
#: code E followed by a value), not inside a number or another code.
_CODE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9.])([A-Z](?:\.[1-9])?)(?![A-Za-z0-9.])")
_VALUE_SEPARATOR_RE = re.compile(r"^\s*[:\-–=]?\s*")


def fold(text: str) -> str:
    """Uppercase and accent-free, for markers and codes."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).upper()


# --- Validators shared by the text and the model paths ----------------------


def clean_vin(value: Any) -> str | None:
    """A 17-character VIN without I, O or Q, or None."""
    if not isinstance(value, str):
        return None
    candidate = re.sub(r"[\s\-]", "", value).upper()
    return candidate if _VIN_RE.match(candidate) else None


def iso_date(value: Any) -> str | None:
    """``YYYY-MM-DD`` from a printed ``dd/mm/yyyy``, ``dd.mm.yyyy`` or ISO date."""
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        return None
    match = _DATE_RE.search(value)
    if match is None:
        return None
    if match.group(4):
        year, month, day = int(match.group(4)), int(match.group(5)), int(match.group(6))
    else:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if parsed.year < 1900 or parsed > date.today().replace(year=date.today().year + 1):
        return None
    return parsed.isoformat()


def to_int(value: Any, *, maximum: int = 1_000_000) -> int | None:
    """A non-negative integer from ``1498``, ``1 498``, ``74 kW`` or ``74.0``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= maximum else None
    if isinstance(value, float):
        return int(value) if value.is_integer() and 0 <= value <= maximum else None
    if not isinstance(value, str):
        return None
    match = _INT_RE.search(value.replace(" ", " "))
    if match is None:
        return None
    number = int(match.group(0).replace(" ", ""))
    return number if 0 <= number <= maximum else None


def to_decimal(value: Any) -> Decimal | None:
    """A non-negative amount from ``162,50``, ``162.50``, ``1 234,56 €`` or a number."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        amount = Decimal(str(value))
        return amount if amount >= 0 else None
    if not isinstance(value, str):
        return None
    match = _DECIMAL_RE.search(value.replace(" ", " "))
    if match is None:
        return None
    raw = match.group(0).replace(" ", "").rstrip(".,")
    # French prints 1.234,56 or 1 234,56; English 1,234.56. The LAST separator
    # followed by one or two digits is the decimal mark.
    if "," in raw and "." in raw:
        raw = (
            raw.replace(".", "").replace(",", ".")
            if raw.rfind(",") > raw.rfind(".")
            else raw.replace(",", "")
        )
    elif "," in raw:
        head, _, tail = raw.rpartition(",")
        raw = f"{head.replace(',', '')}.{tail}" if len(tail) <= 2 else raw.replace(",", "")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


def energy_code(value: Any) -> str | None:
    """A P.3 code the fuel table knows (ES, GO, EL, EE, EH, GL, GH, GP, GN…)."""
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if code in CARTE_GRISE_ENERGY_CODES else None


def eu_category(value: Any) -> str | None:
    """M1, N1, L3e, O2, T1… as printed, dots removed, the ``e`` lowercase."""
    if not isinstance(value, str):
        return None
    code = value.replace(".", "").replace(" ", "").strip().upper()
    if not _EU_CATEGORY_RE.match(code) or len(code) > 5:
        return None
    return code[:-1] + "e" if code.endswith("E") and len(code) > 2 else code


def national_category(value: Any) -> str | None:
    """VP, CTTE, MTL… uppercase alphanumerics, at most ten characters."""
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if re.match(r"^[A-Z0-9]{1,10}$", code) else None


def euro_class(value: Any) -> str | None:
    """V.9 as printed (``EURO 6d-TEMP``, ``EURO6``, ``6AP``), at most twelve characters."""
    if not isinstance(value, str):
        return None
    printed = " ".join(value.split())
    return printed[:12] if printed else None


def free_text(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    printed = " ".join(value.split())
    return printed[:max_length] if printed else None


def country_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if is_country_code(code) else None


# --- Country profiles: markers, plate formats --------------------------------


def _profile_rules() -> list[tuple[str, list[str], list[re.Pattern[str]]]]:
    """``(country, folded markers, plate patterns)`` for every shipped profile."""
    rules: list[tuple[str, list[str], list[re.Pattern[str]]]] = []
    for profile_id in available_profile_ids():
        profile = load_profile(profile_id)
        if profile is None or profile.country is None:
            continue
        certificate = profile.registration_certificate
        patterns: list[re.Pattern[str]] = []
        for raw in certificate.plate_patterns:
            try:
                patterns.append(re.compile(raw))
            except re.error:
                logger.warning("Profile %s: unusable plate pattern %r", profile_id, raw)
        rules.append((profile.country, [fold(m) for m in certificate.markers], patterns))
    return rules


def country_from_markers(text: str) -> str | None:
    """The country whose certificate markers the text carries most of.

    Belgium's French-language certificate and France's both print
    « CERTIFICAT D'IMMATRICULATION »; « RÉPUBLIQUE FRANÇAISE » or « ROYAUME
    DE BELGIQUE » decides. A tie is no answer (the plate format may still
    tell).
    """
    folded = fold(text)
    scores: list[tuple[int, str]] = []
    for country, markers, _patterns in _profile_rules():
        hits = sum(1 for marker in markers if marker and marker in folded)
        if hits:
            scores.append((hits, country))
    if not scores:
        return None
    scores.sort(reverse=True)
    if len(scores) > 1 and scores[0][0] == scores[1][0]:
        return None
    return scores[0][1]


def country_from_plate(plate: str) -> str | None:
    """The first country whose plate format the plate matches."""
    for country, _markers, patterns in _profile_rules():
        if any(p.match(plate) for p in patterns):
            return country
    return None


def plate_for(value: Any, country: str | None) -> tuple[str, str] | None:
    """The plate uppercased and how sure it is: ``high`` when it matches the
    country's format, ``medium`` when the country has no format to check,
    ``low`` when it does not match (a plate is still worth showing)."""
    if not isinstance(value, str):
        return None
    plate = " ".join(value.split()).upper()
    if not plate or not _GENERIC_PLATE_RE.match(plate):
        return None
    if country is None:
        return plate, "medium"
    patterns: list[re.Pattern[str]] = next((p for c, _m, p in _profile_rules() if c == country), [])
    if not patterns:
        return plate, "medium"
    return plate, ("high" if any(p.match(plate) for p in patterns) else "low")


# --- The data ---------------------------------------------------------------


@dataclass
class RegistrationData(DocumentData):
    """What a registration certificate says, by harmonised field."""

    country: str | None = None
    plate: str | None = None
    first_registration: str | None = None
    holder: str | None = None
    make: str | None = None
    type_variant_version: str | None = None
    commercial_name: str | None = None
    vin: str | None = None
    max_mass_kg: int | None = None
    mass_in_service_kg: int | None = None
    eu_category: str | None = None
    national_category: str | None = None
    type_approval: str | None = None
    displacement_cc: int | None = None
    power_kw: int | None = None
    energy_code: str | None = None
    fiscal_power: int | None = None
    seats: int | None = None
    co2_g_km: int | None = None
    euro_class: str | None = None
    last_inspection: str | None = None
    #: Y.1 … Y.6 as printed, by code.
    taxes: dict[str, Decimal] = field(default_factory=dict)
    #: ``high`` for a value that matched a strict shape, ``medium`` for free
    #: text (a make, a holder), ``low`` for a value kept with a doubt.
    field_confidence: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.document_type = DocumentType.REGISTRATION
        if self.vin and not self.extracted_vin:
            self.extracted_vin = self.vin

    def to_dict(self) -> dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "country": self.country,
                "plate": self.plate,
                "first_registration": self.first_registration,
                "holder": self.holder,
                "make": self.make,
                "type_variant_version": self.type_variant_version,
                "commercial_name": self.commercial_name,
                "vin": self.vin,
                "max_mass_kg": self.max_mass_kg,
                "mass_in_service_kg": self.mass_in_service_kg,
                "eu_category": self.eu_category,
                "national_category": self.national_category,
                "type_approval": self.type_approval,
                "displacement_cc": self.displacement_cc,
                "power_kw": self.power_kw,
                "energy_code": self.energy_code,
                "fiscal_power": self.fiscal_power,
                "seats": self.seats,
                "co2_g_km": self.co2_g_km,
                "euro_class": self.euro_class,
                "last_inspection": self.last_inspection,
                "taxes": {code: str(amount) for code, amount in self.taxes.items()},
                "field_confidence": dict(self.field_confidence),
                "warnings": list(self.warnings),
            }
        )
        return base

    def get_validation_warnings(self) -> list[str]:
        warnings = list(self.warnings)
        if not self.vin:
            warnings.append("VIN (E) not found")
        if not self.first_registration:
            warnings.append("Date of first registration (B) not found")
        if not self.make and not self.commercial_name:
            warnings.append("Make (D.1) and model (D.3) not found")
        return warnings


def score(data: RegistrationData) -> float:
    """0 to 100 from the fields found, weighted by how much each one matters."""
    total = sum(weight for name, weight in _WEIGHTS.items() if getattr(data, name))
    return float(min(total, 100))


# --- Assigning a code's value, with its validator ----------------------------


def _assign(data: RegistrationData, code: str, raw: Any) -> bool:
    """Put ``raw`` into the field ``code`` names when it has the right shape.

    Returns whether the value was taken. A field already filled keeps its
    first value (a certificate prints each code once; a second match is
    noise).
    """
    if code in TAX_CODES:
        if code in data.taxes:
            return False
        amount = to_decimal(raw)
        if amount is None:
            return False
        data.taxes[code] = amount
        data.field_confidence[code] = "high"
        return True

    name = CODE_FIELDS[code]
    if getattr(data, name) is not None:
        return False
    confidence = "high"
    value: Any
    if name == "vin":
        value = clean_vin(raw)
    elif name in ("first_registration", "last_inspection"):
        value = iso_date(raw)
    elif name == "plate":
        checked = plate_for(raw, data.country)
        value = checked[0] if checked else None
        confidence = checked[1] if checked else confidence
    elif name in ("max_mass_kg", "mass_in_service_kg"):
        value = to_int(raw, maximum=200_000)
    elif name == "displacement_cc":
        value = to_int(raw, maximum=100_000)
    elif name == "power_kw":
        value = to_int(raw, maximum=2000)
    elif name == "fiscal_power":
        value = to_int(raw, maximum=200)
    elif name == "seats":
        value = to_int(raw, maximum=200)
    elif name == "co2_g_km":
        value = to_int(raw, maximum=999)
    elif name == "energy_code":
        value = energy_code(raw)
    elif name == "eu_category":
        value = eu_category(raw)
    elif name == "national_category":
        value = national_category(raw)
    elif name == "euro_class":
        value = euro_class(raw)
        confidence = "medium"
    elif name == "type_approval":
        value = free_text(raw, max_length=60)
        if value is not None:
            value = _TYPE_APPROVAL_PREFIX_RE.sub(r"\1\2", value)
        confidence = "medium"
    else:  # holder, make, type_variant_version, commercial_name
        value = free_text(raw, max_length=100 if name == "holder" else 50)
        confidence = "medium"
    if value is None:
        return False
    setattr(data, name, value)
    data.field_confidence[name] = confidence
    return True


# --- The text parser --------------------------------------------------------


class EURegistrationCertificateParser(BaseDocumentParser):
    """Reads the text of an EU registration certificate by its harmonised codes."""

    PARSER_NAME = "eu_registration_certificate"
    DOCUMENT_TYPE = DocumentType.REGISTRATION

    #: How many distinct codes a text needs before it is taken for a
    #: certificate when no country marker is printed.
    MIN_CODES = 4

    def can_parse(self, text: str) -> bool:
        if not text or not text.strip():
            return False
        if country_from_markers(text) is not None:
            return True
        return len(self._codes_present(text)) >= self.MIN_CODES

    def parse(self, text: str, *, country: str | None = None, **kwargs: Any) -> RegistrationData:
        """``country`` is a hint (the vehicle's, the person's); the document wins."""
        data = RegistrationData(raw_text=text, parser_name=self.PARSER_NAME)
        data.country = country_from_markers(text) or country_code(country)
        if data.country is not None:
            data.field_confidence["country"] = "high"

        repaired = self._repair(text)
        lines = [line for line in repaired.splitlines()]
        for index, line in enumerate(lines):
            tokens = [
                (m.start(), m.end(), m.group(1))
                for m in _CODE_TOKEN_RE.finditer(line)
                if m.group(1) in KNOWN_CODES
            ]
            for position, (_start, end, code) in enumerate(tokens):
                if code not in CODE_FIELDS and code not in TAX_CODES:
                    continue
                next_start = tokens[position + 1][0] if position + 1 < len(tokens) else len(line)
                raw = _VALUE_SEPARATOR_RE.sub("", line[end:next_start]).strip()
                if not raw and position == len(tokens) - 1 and index + 1 < len(lines):
                    # Label above its value: the next line carries no code.
                    following = lines[index + 1]
                    if not any(
                        m.group(1) in KNOWN_CODES for m in _CODE_TOKEN_RE.finditer(following)
                    ):
                        raw = following.strip()
                if raw:
                    _assign(data, code, raw)

        if data.vin is None:
            # No « E » label read: the only 17-character token is the VIN.
            candidates = {m.group(0) for m in _VIN_ANYWHERE_RE.finditer(repaired)}
            if len(candidates) == 1:
                data.vin = candidates.pop()
                data.field_confidence["vin"] = "medium"
        if data.vin and not data.extracted_vin:
            data.extracted_vin = data.vin
        if data.country is None and data.plate:
            data.country = country_from_plate(data.plate)
            if data.country is not None:
                data.field_confidence["country"] = "medium"
        data.confidence_score = score(data)
        return data

    @staticmethod
    def _repair(text: str) -> str:
        """NFKC, no-break spaces plain, and the codes in ``X.N`` form.

        The case is kept: values are copied as printed (« Euro 6d-TEMP »),
        and the codes are uppercase on every certificate, so a lowercase
        letter is never a code (« e2*2007/46 » stays a type approval).
        """
        plain = unicodedata.normalize("NFKC", text).replace(" ", " ")

        def _join(match: re.Match[str]) -> str:
            code = f"{match.group(1)}.{match.group(2)}"
            return code if code in KNOWN_CODES else match.group(0)

        return _CODE_REPAIR_RE.sub(_join, plain)

    def _codes_present(self, text: str) -> set[str]:
        repaired = self._repair(text)
        return {
            m.group(1)
            for m in _CODE_TOKEN_RE.finditer(repaired)
            if m.group(1) in KNOWN_CODES and m.group(1) != "I"
        }


# --- The model path ---------------------------------------------------------


def from_llm_fields(
    fields: dict[str, Any], *, country: str | None = None, model: str | None = None
) -> RegistrationData:
    """The vision model's JSON (keys ``A``, ``B``, ``C1``…, ``country``) as
    ``RegistrationData``, every value through the same validators as the text
    path: what fails is dropped with a warning naming the code."""
    data = RegistrationData(parser_name=f"vision:{model}" if model else "vision")
    data.country = country_code(fields.get("country")) or country_code(country)
    if data.country is not None:
        data.field_confidence["country"] = "high" if fields.get("country") else "medium"
    for key, raw in fields.items():
        code = LLM_KEY_TO_CODE.get(str(key).replace(".", "").upper())
        if code is None or raw is None or raw == "":
            continue
        if not _assign(data, code, raw):
            data.warnings.append(
                f"{code}: value {raw!r} does not look like a {CODE_FIELDS.get(code, 'tax amount')}; dropped"
            )
    if data.vin and not data.extracted_vin:
        data.extracted_vin = data.vin
    if data.country is None and data.plate:
        data.country = country_from_plate(data.plate)
        if data.country is not None:
            data.field_confidence["country"] = "medium"
    data.confidence_score = score(data)
    return data
