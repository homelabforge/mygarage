"""Insurance document parsers with provider-specific implementations.

The French parser lives in `insurance_fr.py` (#211); `from_llm_fields` below
turns a vision model's answer (`document_prompts/insurance_policy.py`) into
the same `InsuranceData` the text parsers produce, every value through the
same validators.
"""

import logging
import re
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.constants.insurance import clean_no_claims_class
from app.utils.household_time import household_today
from app.utils.insurance_coverages import COVERAGE_BY_KEY, coverage_payload, parse_coverage_lines

from .base import BaseDocumentParser, DocumentData, DocumentType

logger = logging.getLogger(__name__)

#: A registration plate as a policy prints it: letters, digits, spaces and
#: dashes, 4 to 12 characters, at least one digit (« AB-123-CD », « 1234 AB
#: 56 », « M-AB 1234 »).
_PLATE_RE = re.compile(r"^(?=.*\d)[A-Z0-9][A-Z0-9 -]{2,10}[A-Z0-9]$")
#: The French SIV plate, with the dashes a document may print as spaces.
_SIV_PLATE_RE = re.compile(r"\b([A-Z]{2})[- ]?(\d{3})[- ]?([A-Z]{2})\b")

#: The formula printed on a policy → the stored policy type. Longest and most
#: specific first, since « tiers étendu » contains « tiers » and « tous
#: risques » may be quoted in a third-party policy's marketing text, which
#: is why `classify_formula` looks for a labelled formula before a bare word.
_FORMULA_RULES: tuple[tuple[str, str], ...] = (
    # Full cover: France, Germany, Italy, Spain, English.
    (r"tous\s+risques", "Full Coverage"),
    (r"\bvollkasko\b", "Full Coverage"),
    (r"\bkasko\s+completa\b|\bkasko\b(?!\s+parziale)", "Full Coverage"),
    (r"\btodo\s+riesgo\b", "Full Coverage"),
    (r"\bfull\s+coverage\b|\bfully\s+comprehensive\b", "Full Coverage"),
    # Third party extended: a third-party formula plus theft, fire, glass…
    (
        r"tiers\s*(?:étendu|etendu|\+|plus|confort|intermédiaire|intermediaire|privilège|privilege)",
        "Third Party Extended",
    ),
    (r"formule\s+(?:intermédiaire|intermediaire|confort|médiane|mediane)", "Third Party Extended"),
    (r"\bteilkasko\b", "Third Party Extended"),
    (r"\bkasko\s+parziale\b|\bfurto\s+(?:e|ed)\s+incendio\b", "Third Party Extended"),
    (r"\bterceros\s+(?:ampliado|con\s+lunas|\+)", "Third Party Extended"),
    (r"\bthird\s+party\s*,?\s+fire\s+and\s+theft\b|\btpft\b", "Third Party Extended"),
    # Third party only.
    (
        r"\bau\s+tiers\b|\btiers\s+(?:simple|essentiel|seul|minimum)\b|\bformule\s+tiers\b",
        "Third Party",
    ),
    (r"responsabilit[ée]\s+civile\s+(?:seule|uniquement|obligatoire)", "Third Party"),
    (
        r"\b(?:kfz-)?haftpflicht(?:versicherung)?\s+(?:nur|only)\b|\bnur\s+haftpflicht\b",
        "Third Party",
    ),
    (r"\bsolo\s+rc\b|\brc\s+auto\s+(?:base|solo)\b", "Third Party"),
    (
        r"\b(?:solo\s+)?(?:a\s+)?terceros\s+(?:básico|basico|simple)\b|\ba\s+terceros\b",
        "Third Party",
    ),
    # Not a bare « third party »: a North American page says it of the other
    # driver, and this classifier runs on every parser's text.
    (r"\bthird\s+party\s+only\b|\bthird\s+party\s+liability\s+only\b", "Third Party"),
)
#: A formula printed after its label: « Formule : Tous risques », « Formel »,
#: « Tipo di polizza », « Modalidad ».
_FORMULA_LABEL_RE = re.compile(
    r"(?:formule|formula|forme\s+de\s+contrat|option\s+choisie|niveau\s+de\s+garantie|"
    r"deckung|deckungsart|tarif|tipo\s+di\s+polizza|modalidad|cover(?:age)?\s+type|policy\s+type)"
    r"\s*[:\-–]?\s*([^\n]{3,60})",
    re.IGNORECASE,
)


def classify_formula(text: str | None) -> str | None:
    """The stored policy type a printed formula means, or None.

    A labelled formula (« Formule : tiers étendu ») is read first; the whole
    text only when the label is missing. Full cover beats extended beats
    third party, since the wider formula includes the narrower words.
    """
    if not text:
        return None
    labelled = _FORMULA_LABEL_RE.search(text)
    for candidate in ((labelled.group(1) if labelled else None), text):
        if not candidate:
            continue
        lowered = candidate.lower()
        for pattern, policy_type in _FORMULA_RULES:
            if re.search(pattern, lowered):
                return policy_type
    return None


def clean_plate(value: Any) -> str | None:
    """A registration plate as the garage stores it, upper-case, or None.

    A French SIV plate is written with its dashes whatever the document
    printed (« AB 123 CD » → « AB-123-CD »), which is how the vehicle form
    stores it, so a plate match finds the vehicle.
    """
    if not isinstance(value, str):
        return None
    printed = " ".join(value.split()).upper()
    siv = _SIV_PLATE_RE.fullmatch(printed)
    if siv:
        return "-".join(siv.groups())
    return printed if _PLATE_RE.match(printed) else None


def plates_in(text: str) -> list[str]:
    """Every French SIV plate printed in the text, dashed, in order, once."""
    found: list[str] = []
    for match in _SIV_PLATE_RE.finditer(text.upper()):
        plate = "-".join(match.groups())
        if plate not in found:
            found.append(plate)
    return found


@dataclass
class InsuranceData(DocumentData):
    """Structured data extracted from insurance documents."""

    # Provider info
    provider: str | None = None

    # Policy details
    policy_number: str | None = None
    policy_type: str | None = None  # Liability/Comprehensive/Collision/Full Coverage/Other

    # Dates
    start_date: str | None = None  # YYYY-MM-DD format
    end_date: str | None = None

    # Financial
    premium_amount: Decimal | None = None
    premium_frequency: str | None = None  # Monthly/Quarterly/Semi-Annual/Annual
    deductible: Decimal | None = None

    #: The no-claims class printed (CRM 0.50, SF 12, classe 1…), #211.
    no_claims_class: str | None = None

    # Vehicle info
    vehicles_found: list[str] = field(default_factory=list)
    #: The registration plates printed, for a policy that names no VIN (a
    #: French avis d'échéance usually prints the plate alone), #211.
    plates_found: list[str] = field(default_factory=list)
    #: Per-VIN figures for EVERY vehicle on the document, where the parser can
    #: find a per-vehicle section. A household policy covers several vehicles,
    #: so the target VIN's figures alone discard most of the declarations page.
    vehicle_details: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    #: Standard coverages read off the WHOLE document, for vehicles with no
    #: section of their own. Mapped onto the catalogue in
    #: `app.utils.insurance_coverages`.
    coverages: list[dict[str, str | None]] = field(default_factory=list)
    #: Per-VIN standard coverages, where the page gives that vehicle a section.
    #: Kept apart from `vehicle_details`, which is money only and is
    #: stringified wholesale on the way out.
    vehicle_coverages: dict[str, list[dict[str, str | None]]] = field(default_factory=dict)
    #: Coverage names the document printed that the catalogue does not know
    #: (the vision path lists them; the text path keeps such lines as named
    #: fields in the same read), #211.
    unmatched_coverages: list[str] = field(default_factory=list)

    # Notes
    notes: str | None = None

    # Per-field confidence
    field_confidence: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.document_type = DocumentType.INSURANCE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        base = super().to_dict()
        base.update(
            {
                "provider": self.provider,
                "policy_number": self.policy_number,
                "policy_type": self.policy_type,
                "start_date": self.start_date,
                "end_date": self.end_date,
                "premium_amount": str(self.premium_amount) if self.premium_amount else None,
                "premium_frequency": self.premium_frequency,
                "deductible": str(self.deductible) if self.deductible else None,
                "no_claims_class": self.no_claims_class,
                "coverages": self.coverages,
                "vehicles_found": self.vehicles_found,
                "plates_found": self.plates_found,
                "vehicle_details": {
                    vin: {name: str(amount) for name, amount in figures.items()}
                    for vin, figures in self.vehicle_details.items()
                },
                "vehicle_coverages": self.vehicle_coverages,
                "unmatched_coverages": self.unmatched_coverages,
                "notes": self.notes,
                "field_confidence": self.field_confidence,
            }
        )
        return base

    def get_validation_warnings(self) -> list[str]:
        """Return list of validation warnings."""
        warnings = []

        if not self.policy_number:
            warnings.append("Policy number not found")
        if not self.start_date or not self.end_date:
            warnings.append("Policy dates not fully extracted")
        if not self.premium_amount:
            warnings.append("Premium amount not found")
        if not self.vehicles_found and not self.plates_found:
            warnings.append("No VINs or registration plates found in document")

        return warnings


class InsuranceDocumentParser(BaseDocumentParser):
    """Base class for insurance document parsers."""

    DOCUMENT_TYPE = DocumentType.INSURANCE
    PROVIDER_NAME: str = "Unknown"

    @abstractmethod
    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        """Parse insurance document text."""
        pass

    def parse_document(
        self, text: str, *, target_vin: str | None = None, **kwargs: Any
    ) -> InsuranceData:
        """Parse, then read the standard coverages off the page.

        Reading coverages matches PHRASES, not layouts, so it is the same work
        for every insurer and belongs here rather than inside any one parser.
        Callers use this, not `parse`, or the four providers that never
        implemented a coverage read would return none at all.
        """
        data = self.parse(text, target_vin=target_vin, **kwargs)
        self._fill_coverages(data, text)
        return data

    def _fill_coverages(self, data: InsuranceData, text: str) -> None:
        """Document-wide coverages, plus per-vehicle ones where a page has
        sections. Only a vehicle with NO section of its own falls back to the
        document-wide read, which is the best the page offers for it."""
        data.coverages = coverage_payload(parse_coverage_lines(text).coverages)
        for found_vin in data.vehicles_found:
            section = self._vin_section(text, found_vin)
            if section is None:
                continue
            # Keyed even when the section names no coverage, so the caller can
            # tell "this vehicle's own section listed none" from "this vehicle
            # has no section". Falling back for the first would hand it the
            # coverages of whichever vehicle the page listed first.
            data.vehicle_coverages[found_vin.upper()] = coverage_payload(
                parse_coverage_lines(section).coverages
            )

    @staticmethod
    def _vin_section(text: str, vin: str) -> str | None:
        """The part of the page that belongs to one VIN, up to the next one."""
        match = re.search(
            rf"VIN\s+{re.escape(vin)}.*?(?=VIN\s+[A-HJ-NPR-Z0-9]{{17}}|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        return match.group(0) if match else None

    def _parse_date(self, date_str: str) -> str | None:
        """Parse various date formats to YYYY-MM-DD."""
        date_formats = [
            "%B %d, %Y",  # August 26, 2025
            "%b %d, %Y",  # Aug 26, 2025
            "%m/%d/%Y",  # 08/26/2025
            "%m-%d-%Y",  # 08-26-2025
            "%Y-%m-%d",  # 2025-08-26
            "%d/%m/%Y",  # 26/08/2025
        ]

        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None

    @staticmethod
    def _determine_frequency(start_date: str, end_date: str) -> str:
        """Determine payment frequency from policy period."""
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            months = (end.year - start.year) * 12 + end.month - start.month

            if 5 <= months <= 7:
                return "Semi-Annual"
            elif 11 <= months <= 13:
                return "Annual"
            elif 2 <= months <= 4:
                return "Quarterly"
            else:
                return "Monthly"
        except ValueError:
            return "Semi-Annual"

    def _determine_policy_type(self, text: str) -> str:
        """Determine policy type from coverage information."""
        text_lower = text.lower()

        # A European formula printed on the page names the type outright.
        formula = classify_formula(text)
        if formula is not None:
            return formula
        if all(c in text_lower for c in ["comprehensive", "collision", "liability"]):
            return "Full Coverage"
        elif "comprehensive" in text_lower and "collision" in text_lower:
            return "Full Coverage"
        elif "comprehensive" in text_lower:
            return "Comprehensive"
        elif "collision" in text_lower:
            return "Collision"
        elif "liability" in text_lower:
            return "Liability"
        else:
            return "Other"

    @staticmethod
    def _calculate_confidence(data: InsuranceData) -> float:
        """Calculate overall confidence score."""
        score = 0.0

        # Core fields (60 points)
        if data.policy_number:
            score += 15
        if data.start_date:
            score += 10
        if data.end_date:
            score += 10
        if data.premium_amount:
            score += 15
        if data.provider:
            score += 10

        # Secondary fields (40 points)
        if data.deductible:
            score += 10
        if data.coverages:
            score += 10
        if data.policy_type and data.policy_type != "Other":
            score += 10
        if data.vehicles_found:
            score += 10

        return score


class ProgressiveInsuranceParser(InsuranceDocumentParser):
    """Parser for Progressive Insurance documents."""

    PARSER_NAME = "Progressive"
    PROVIDER_NAME = "Progressive"

    PATTERNS = {
        "policy_number": [
            r"Auto\s+(\d{10,})",
            r"Policy\s+(?:Number|#):\s*(\d+)",
            r"Policy:\s*Auto\s+(\d+)",
            r"Auto Policy\s+#?\s*(\d+)",
        ],
        "policy_period": [
            r"Policy period\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s*[-–]\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–]\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"Effective\s+date[:\s]*([A-Za-z]+\s+\d{1,2},\s+\d{4}).*?(?:Expir|End)[^\d]*(\d{1,2}/\d{1,2}/\d{4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})",
        ],
        "total_premium": [
            r"Total\s+policy\s+premium\s*\$?([\d,]+\.?\d*)",
            r"Total\s+premium\s*:?\s*\$?([\d,]+\.?\d*)",
            r"Premium\s+total\s*:?\s*\$?([\d,]+\.?\d*)",
        ],
        "vehicle_premium": [
            r"Total\s+vehicle\s+[Pp]remium\s*\$?([\d,]+\.?\d*)",
        ],
        "deductible": [
            r"\$(\d+)\s+[Dd]eductible",
            r"[Dd]eductible[:\s]*\$?(\d+)",
            r"Comprehensive.*?\$(\d+)",
            r"Collision.*?\$(\d+)",
        ],
    }

    def can_parse(self, text: str) -> bool:
        """Check if text appears to be from Progressive."""
        indicators = ["progressive", "mayfield village", "oh 44143"]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in indicators)

    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        """Parse Progressive insurance document."""
        data = InsuranceData(
            provider=self.PROVIDER_NAME,
            parser_name=self.PARSER_NAME,
            raw_text=text,
        )

        # Extract policy number
        policy_num = self._extract_pattern(text, self.PATTERNS["policy_number"])
        if policy_num:
            data.policy_number = policy_num
            data.field_confidence["policy_number"] = "high"

        # Extract policy period
        period = self._extract_policy_period(text)
        if period:
            data.start_date = period["start"]
            data.end_date = period["end"]
            data.field_confidence["dates"] = "high"

            # Determine frequency
            data.premium_frequency = self._determine_frequency(data.start_date, data.end_date)

        # Extract total premium
        premium = self._extract_pattern(text, self.PATTERNS["total_premium"])
        if premium:
            data.premium_amount = self._parse_currency(premium)
            data.field_confidence["premium_amount"] = "high"

        # Extract all VINs
        data.vehicles_found = self._extract_all_vins(text)
        for found_vin in data.vehicles_found:
            figures = self._extract_vehicle_specific_data(text, found_vin)
            if figures:
                data.vehicle_details[found_vin.upper()] = figures

        # If target VIN specified, extract vehicle-specific data
        if target_vin and target_vin.upper() in [v.upper() for v in data.vehicles_found]:
            vehicle_data = self._extract_vehicle_specific_data(text, target_vin)
            if vehicle_data.get("premium_amount"):
                data.premium_amount = vehicle_data["premium_amount"]
                data.field_confidence["premium_amount"] = "high"
            if vehicle_data.get("deductible"):
                data.deductible = vehicle_data["deductible"]
                data.field_confidence["deductible"] = "medium"
            data.extracted_vin = target_vin.upper()

        # Extract deductible if not already set
        if not data.deductible:
            deductible = self._extract_pattern(text, self.PATTERNS["deductible"])
            if deductible:
                data.deductible = self._parse_currency(deductible)
                data.field_confidence["deductible"] = "medium"

        # Determine policy type
        data.policy_type = self._determine_policy_type(text)

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        # Add note
        data.notes = f"Auto-imported from Progressive PDF on {household_today().isoformat()}"

        return data

    def _extract_policy_period(self, text: str) -> dict[str, str] | None:
        """Extract policy period dates."""
        for pattern in self.PATTERNS["policy_period"]:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                start_str = match.group(1)
                end_str = match.group(2)

                start_date = self._parse_date(start_str)
                end_date = self._parse_date(end_str)

                if start_date and end_date:
                    return {"start": start_date, "end": end_date}
        return None

    def _extract_vehicle_specific_data(self, text: str, vin: str) -> dict[str, Any]:
        """Extract vehicle-specific data for a given VIN."""
        data = {}

        section = self._vin_section(text, vin)
        if section:
            # Extract vehicle premium
            vehicle_premium = self._extract_pattern(section, self.PATTERNS["vehicle_premium"])
            if vehicle_premium:
                data["premium_amount"] = self._parse_currency(vehicle_premium)

            # Extract deductible
            deductible = self._extract_pattern(section, self.PATTERNS["deductible"])
            if deductible:
                data["deductible"] = self._parse_currency(deductible)

        return data


class StateFarmInsuranceParser(InsuranceDocumentParser):
    """Parser for State Farm Insurance documents."""

    PARSER_NAME = "StateFarm"
    PROVIDER_NAME = "State Farm"

    PATTERNS = {
        "policy_number": [
            r"Policy\s+(?:Number|#)[:\s]*([A-Z0-9\-]+)",
            r"Policy[:\s]*([A-Z0-9]{3,}\-[A-Z0-9\-]+)",
        ],
        "policy_period": [
            r"(?:Policy\s+)?[Pp]eriod[:\s]*(\d{1,2}/\d{1,2}/\d{4})\s*(?:to|[-–])\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"[Ee]ffective[:\s]*(\d{1,2}/\d{1,2}/\d{4}).*?[Ee]xpir\w*[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
        ],
        "total_premium": [
            r"[Tt]otal\s+[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
            r"[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
            r"[Aa]mount\s+[Dd]ue[:\s]*\$?([\d,]+\.?\d*)",
        ],
        "deductible": [
            r"[Dd]eductible[:\s]*\$?(\d+)",
            r"\$(\d+)\s+[Dd]eductible",
        ],
    }

    def can_parse(self, text: str) -> bool:
        """Check if text appears to be from State Farm."""
        indicators = ["state farm", "bloomington", "il 61710"]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in indicators)

    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        """Parse State Farm insurance document."""
        data = InsuranceData(
            provider=self.PROVIDER_NAME,
            parser_name=self.PARSER_NAME,
            raw_text=text,
        )

        # Extract policy number
        policy_num = self._extract_pattern(text, self.PATTERNS["policy_number"])
        if policy_num:
            data.policy_number = policy_num
            data.field_confidence["policy_number"] = "high"

        # Extract policy period
        for pattern in self.PATTERNS["policy_period"]:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                start_date = self._parse_date(match.group(1))
                end_date = self._parse_date(match.group(2))
                if start_date and end_date:
                    data.start_date = start_date
                    data.end_date = end_date
                    data.field_confidence["dates"] = "high"
                    data.premium_frequency = self._determine_frequency(start_date, end_date)
                    break

        # Extract premium
        premium = self._extract_pattern(text, self.PATTERNS["total_premium"])
        if premium:
            data.premium_amount = self._parse_currency(premium)
            data.field_confidence["premium_amount"] = "high"

        # Extract all VINs
        data.vehicles_found = self._extract_all_vins(text)
        if target_vin:
            data.extracted_vin = target_vin.upper()

        # Extract deductible
        deductible = self._extract_pattern(text, self.PATTERNS["deductible"])
        if deductible:
            data.deductible = self._parse_currency(deductible)
            data.field_confidence["deductible"] = "medium"

        # Determine policy type
        data.policy_type = self._determine_policy_type(text)

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        data.notes = f"Auto-imported from State Farm PDF on {household_today().isoformat()}"

        return data


class GeicoInsuranceParser(InsuranceDocumentParser):
    """Parser for GEICO Insurance documents."""

    PARSER_NAME = "Geico"
    PROVIDER_NAME = "GEICO"

    PATTERNS = {
        "policy_number": [
            r"[Pp]olicy\s*(?:#|[Nn]umber)?[:\s]*(\d{10,})",
            r"[Pp]olicy[:\s]*(\d+-\d+-\d+)",
        ],
        "policy_period": [
            r"[Pp]olicy\s+[Pp]eriod[:\s]*(\d{1,2}/\d{1,2}/\d{2,4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{2,4})",
            r"[Ee]ffective[:\s]*(\d{1,2}/\d{1,2}/\d{4}).*?[Ee]xpir\w*[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
        ],
        "total_premium": [
            r"[Tt]otal\s+[Pp]olicy\s+[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
            r"[Ss]ix[- ][Mm]onth\s+[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
            r"[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
        ],
        "deductible": [
            r"[Dd]eductible[:\s]*\$?(\d+)",
            r"\$(\d+)\s+[Dd]ed(?:uctible)?",
        ],
    }

    def can_parse(self, text: str) -> bool:
        """Check if text appears to be from GEICO."""
        indicators = ["geico", "government employees insurance"]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in indicators)

    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        """Parse GEICO insurance document."""
        data = InsuranceData(
            provider=self.PROVIDER_NAME,
            parser_name=self.PARSER_NAME,
            raw_text=text,
        )

        # Extract policy number
        policy_num = self._extract_pattern(text, self.PATTERNS["policy_number"])
        if policy_num:
            data.policy_number = policy_num
            data.field_confidence["policy_number"] = "high"

        # Extract policy period
        for pattern in self.PATTERNS["policy_period"]:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                start_date = self._parse_date(match.group(1))
                end_date = self._parse_date(match.group(2))
                if start_date and end_date:
                    data.start_date = start_date
                    data.end_date = end_date
                    data.field_confidence["dates"] = "high"
                    data.premium_frequency = self._determine_frequency(start_date, end_date)
                    break

        # Extract premium
        premium = self._extract_pattern(text, self.PATTERNS["total_premium"])
        if premium:
            data.premium_amount = self._parse_currency(premium)
            data.field_confidence["premium_amount"] = "high"

        # Extract all VINs
        data.vehicles_found = self._extract_all_vins(text)
        if target_vin:
            data.extracted_vin = target_vin.upper()

        # Extract deductible
        deductible = self._extract_pattern(text, self.PATTERNS["deductible"])
        if deductible:
            data.deductible = self._parse_currency(deductible)
            data.field_confidence["deductible"] = "medium"

        # Determine policy type
        data.policy_type = self._determine_policy_type(text)

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        data.notes = f"Auto-imported from GEICO PDF on {household_today().isoformat()}"

        return data


class AllstateInsuranceParser(InsuranceDocumentParser):
    """Parser for Allstate Insurance documents."""

    PARSER_NAME = "Allstate"
    PROVIDER_NAME = "Allstate"

    PATTERNS = {
        "policy_number": [
            r"[Pp]olicy\s*(?:#|[Nn]umber)?[:\s]*(\d{3}\s*\d{3}\s*\d{3})",
            r"[Pp]olicy[:\s]*([A-Z0-9]{9,})",
        ],
        "policy_period": [
            r"[Pp]olicy\s+[Pp]eriod[:\s]*(\d{1,2}/\d{1,2}/\d{4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{4})",
        ],
        "total_premium": [
            r"[Tt]otal\s+[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
            r"[Pp]olicy\s+[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
        ],
        "deductible": [
            r"[Dd]eductible[:\s]*\$?(\d+)",
        ],
    }

    def can_parse(self, text: str) -> bool:
        """Check if text appears to be from Allstate."""
        indicators = ["allstate", "you're in good hands"]
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in indicators)

    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        """Parse Allstate insurance document."""
        data = InsuranceData(
            provider=self.PROVIDER_NAME,
            parser_name=self.PARSER_NAME,
            raw_text=text,
        )

        # Extract policy number
        policy_num = self._extract_pattern(text, self.PATTERNS["policy_number"])
        if policy_num:
            data.policy_number = policy_num.replace(" ", "")
            data.field_confidence["policy_number"] = "high"

        # Extract policy period
        for pattern in self.PATTERNS["policy_period"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_date = self._parse_date(match.group(1))
                end_date = self._parse_date(match.group(2))
                if start_date and end_date:
                    data.start_date = start_date
                    data.end_date = end_date
                    data.field_confidence["dates"] = "high"
                    data.premium_frequency = self._determine_frequency(start_date, end_date)
                    break

        # Extract premium
        premium = self._extract_pattern(text, self.PATTERNS["total_premium"])
        if premium:
            data.premium_amount = self._parse_currency(premium)
            data.field_confidence["premium_amount"] = "high"

        # Extract all VINs
        data.vehicles_found = self._extract_all_vins(text)
        if target_vin:
            data.extracted_vin = target_vin.upper()

        # Extract deductible
        deductible = self._extract_pattern(text, self.PATTERNS["deductible"])
        if deductible:
            data.deductible = self._parse_currency(deductible)
            data.field_confidence["deductible"] = "medium"

        # Determine policy type
        data.policy_type = self._determine_policy_type(text)

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        data.notes = f"Auto-imported from Allstate PDF on {household_today().isoformat()}"

        return data


class GenericInsuranceParser(InsuranceDocumentParser):
    """Generic fallback parser for unknown insurance providers."""

    PARSER_NAME = "GenericInsurance"
    PROVIDER_NAME = "Unknown"

    PATTERNS = {
        "policy_number": [
            r"[Pp]olicy\s*(?:#|[Nn]o\.?|[Nn]umber)?[:\s]*([A-Z0-9\-]{6,})",
        ],
        "policy_period": [
            r"(\d{1,2}/\d{1,2}/\d{4})\s*[-–to]+\s*(\d{1,2}/\d{1,2}/\d{4})",
            r"([A-Za-z]+\s+\d{1,2},\s+\d{4})\s*[-–to]+\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        ],
        "total_premium": [
            r"[Tt]otal[:\s]*\$?([\d,]+\.?\d*)",
            r"[Pp]remium[:\s]*\$?([\d,]+\.?\d*)",
            r"[Aa]mount[:\s]*\$?([\d,]+\.?\d*)",
        ],
        "deductible": [
            r"[Dd]eductible[:\s]*\$?(\d+)",
            r"\$(\d+)\s+[Dd]ed",
        ],
        "provider": [
            r"(Progressive|State Farm|Geico|GEICO|Allstate|Farmers|USAA|Nationwide|Liberty Mutual|Travelers)",
        ],
    }

    def can_parse(self, text: str) -> bool:
        """Generic parser can always parse - used as fallback."""
        return True

    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        """Parse insurance document with generic patterns."""
        data = InsuranceData(
            parser_name=self.PARSER_NAME,
            raw_text=text,
        )

        # Try to detect provider
        provider = self._extract_pattern(text, self.PATTERNS["provider"])
        if provider:
            data.provider = provider
            data.field_confidence["provider"] = "medium"
        else:
            data.provider = self.PROVIDER_NAME

        # Extract policy number
        policy_num = self._extract_pattern(text, self.PATTERNS["policy_number"])
        if policy_num:
            data.policy_number = policy_num
            data.field_confidence["policy_number"] = "medium"

        # Extract policy period
        for pattern in self.PATTERNS["policy_period"]:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_date = self._parse_date(match.group(1))
                end_date = self._parse_date(match.group(2))
                if start_date and end_date:
                    data.start_date = start_date
                    data.end_date = end_date
                    data.field_confidence["dates"] = "medium"
                    data.premium_frequency = self._determine_frequency(start_date, end_date)
                    break

        # Extract premium
        premium = self._extract_pattern(text, self.PATTERNS["total_premium"])
        if premium:
            data.premium_amount = self._parse_currency(premium)
            data.field_confidence["premium_amount"] = "low"

        # Extract all VINs
        data.vehicles_found = self._extract_all_vins(text)
        if target_vin:
            data.extracted_vin = target_vin.upper()

        # Extract deductible
        deductible = self._extract_pattern(text, self.PATTERNS["deductible"])
        if deductible:
            data.deductible = self._parse_currency(deductible)
            data.field_confidence["deductible"] = "low"

        # Determine policy type
        data.policy_type = self._determine_policy_type(text)

        # Calculate confidence with penalty for generic
        data.confidence_score = self._calculate_confidence(data) * 0.7

        data.notes = f"Auto-imported from PDF on {household_today().isoformat()} (generic parser)"

        return data


# ---------------------------------------------------------------------------
# The vision model's answer (#211)
# ---------------------------------------------------------------------------

_FREQUENCY_WORDS: dict[str, str] = {
    "monthly": "Monthly",
    "mensuel": "Monthly",
    "mensuelle": "Monthly",
    "monatlich": "Monthly",
    "mensile": "Monthly",
    "mensual": "Monthly",
    "quarterly": "Quarterly",
    "trimestriel": "Quarterly",
    "trimestrielle": "Quarterly",
    "vierteljährlich": "Quarterly",
    "trimestrale": "Quarterly",
    "trimestral": "Quarterly",
    "semi-annual": "Semi-Annual",
    "semiannual": "Semi-Annual",
    "half-yearly": "Semi-Annual",
    "semestriel": "Semi-Annual",
    "semestrielle": "Semi-Annual",
    "halbjährlich": "Semi-Annual",
    "semestrale": "Semi-Annual",
    "semestral": "Semi-Annual",
    "annual": "Annual",
    "yearly": "Annual",
    "annuel": "Annual",
    "annuelle": "Annual",
    "jährlich": "Annual",
    "annuale": "Annual",
    "anual": "Annual",
}


def frequency_from_words(value: Any) -> str | None:
    """`Monthly` / `Quarterly` / `Semi-Annual` / `Annual` from a printed word."""
    if not isinstance(value, str):
        return None
    return _FREQUENCY_WORDS.get(value.strip().lower())


def from_llm_fields(fields: dict[str, Any], *, model: str | None = None) -> InsuranceData:
    """The vision model's JSON (`document_prompts/insurance_policy.py`) as
    `InsuranceData`, every value through the same validators as the text
    path: what fails is dropped with a warning naming the key, in
    `field_confidence` as `rejected`."""
    from .registration import clean_vin, free_text, iso_date, to_decimal

    data = InsuranceData(parser_name=f"vision:{model}" if model else "vision")
    confidence = data.field_confidence

    def take(key: str, value: Any, kept: Any) -> None:
        if value in (None, ""):
            return
        confidence[key] = "high" if kept is not None else "rejected"

    insurer = free_text(fields.get("insurer"), max_length=100)
    take("provider", fields.get("insurer"), insurer)
    data.provider = insurer or "Unknown"

    number = free_text(fields.get("policy_number"), max_length=50)
    take("policy_number", fields.get("policy_number"), number)
    data.policy_number = number

    start, end = iso_date(fields.get("start_date")), iso_date(fields.get("end_date"))
    if fields.get("start_date") or fields.get("end_date"):
        confidence["dates"] = "high" if start and end else "rejected"
    data.start_date, data.end_date = start, end

    premium = to_decimal(fields.get("premium"))
    take("premium_amount", fields.get("premium"), premium)
    data.premium_amount = premium

    frequency = frequency_from_words(fields.get("payment_frequency"))
    if frequency is None and start and end:
        frequency = InsuranceDocumentParser._determine_frequency(start, end)
    data.premium_frequency = frequency

    deductible = to_decimal(fields.get("deductible"))
    take("deductible", fields.get("deductible"), deductible)
    data.deductible = deductible

    policy_type = classify_formula(fields.get("policy_type"))
    take("policy_type", fields.get("policy_type"), policy_type)
    data.policy_type = policy_type or "Other"

    no_claims = clean_no_claims_class(fields.get("no_claims_class"))
    take("no_claims_class", fields.get("no_claims_class"), no_claims)
    data.no_claims_class = no_claims

    for raw in fields.get("vins") or []:
        vin = clean_vin(raw)
        if vin and vin not in data.vehicles_found:
            data.vehicles_found.append(vin)
    for raw in fields.get("plates") or []:
        plate = clean_plate(raw)
        if plate and plate not in data.plates_found:
            data.plates_found.append(plate)

    # Each coverage the model listed becomes a line the catalogue parser
    # reads, so a FR/DE/IT/ES garantie lands on the same row a text PDF's
    # would; a name outside the catalogue is reported, never guessed.
    lines: list[str] = []
    for item in fields.get("coverages") or []:
        if not isinstance(item, dict):
            continue
        name = free_text(item.get("name"), max_length=80)
        if not name:
            continue
        limit = to_decimal(item.get("limit"))
        # The amount is a LIMIT: it fills a coverage that has a limit slot
        # and is dropped for one that has none (a franchise the model
        # called a limit must not become a deductible by position).
        probe = parse_coverage_lines(name).coverages
        has_limit = bool(probe) and COVERAGE_BY_KEY[probe[0].key].primary is not None
        lines.append(f"{name} {limit} €" if limit is not None and has_limit else name)
    parse = parse_coverage_lines("\n".join(lines))
    data.coverages = coverage_payload(parse.coverages)
    for label, _value in parse.fields:
        data.unmatched_coverages.append(label)
    data.unmatched_coverages.extend(parse.notes)

    data.confidence_score = InsuranceDocumentParser._calculate_confidence(data)
    data.notes = f"Read by the vision model on {household_today().isoformat()}"
    return data
