"""Insurance document parsers with provider-specific implementations."""

# pyright: reportIncompatibleMethodOverride=false, reportArgumentType=false

import logging
import re
from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from .base import BaseDocumentParser, DocumentData, DocumentType

logger = logging.getLogger(__name__)


@dataclass
class InsuranceData(DocumentData):
    """Structured data extracted from insurance documents."""

    # Provider info
    provider: Optional[str] = None

    # Policy details
    policy_number: Optional[str] = None
    policy_type: Optional[str] = (
        None  # Liability/Comprehensive/Collision/Full Coverage/Other
    )

    # Dates
    start_date: Optional[str] = None  # YYYY-MM-DD format
    end_date: Optional[str] = None

    # Financial
    premium_amount: Optional[Decimal] = None
    premium_frequency: Optional[str] = None  # Monthly/Quarterly/Semi-Annual/Annual
    deductible: Optional[Decimal] = None
    coverage_limits: Optional[str] = None

    # Vehicle info
    vehicles_found: list[str] = field(default_factory=list)

    # Notes
    notes: Optional[str] = None

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
                "premium_amount": str(self.premium_amount)
                if self.premium_amount
                else None,
                "premium_frequency": self.premium_frequency,
                "deductible": str(self.deductible) if self.deductible else None,
                "coverage_limits": self.coverage_limits,
                "vehicles_found": self.vehicles_found,
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
        if not self.vehicles_found:
            warnings.append("No VINs found in document")

        return warnings


class InsuranceDocumentParser(BaseDocumentParser):
    """Base class for insurance document parsers."""

    DOCUMENT_TYPE = DocumentType.INSURANCE
    PROVIDER_NAME: str = "Unknown"

    @abstractmethod
    def parse(self, text: str, target_vin: Optional[str] = None) -> InsuranceData:
        """Parse insurance document text."""
        pass

    def _parse_date(self, date_str: str) -> Optional[str]:
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

    def _determine_frequency(self, start_date: str, end_date: str) -> str:
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

    def _calculate_confidence(self, data: InsuranceData) -> float:
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
        if data.coverage_limits:
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

    def parse(self, text: str, target_vin: Optional[str] = None) -> InsuranceData:
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
            data.premium_frequency = self._determine_frequency(
                data.start_date, data.end_date
            )

        # Extract total premium
        premium = self._extract_pattern(text, self.PATTERNS["total_premium"])
        if premium:
            data.premium_amount = self._parse_currency(premium)
            data.field_confidence["premium_amount"] = "high"

        # Extract all VINs
        data.vehicles_found = self._extract_all_vins(text)

        # If target VIN specified, extract vehicle-specific data
        if target_vin and target_vin.upper() in [
            v.upper() for v in data.vehicles_found
        ]:
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

        # Extract coverage limits
        data.coverage_limits = self._extract_coverage_limits(text)
        if data.coverage_limits:
            data.field_confidence["coverage_limits"] = "medium"

        # Calculate confidence
        data.confidence_score = self._calculate_confidence(data)

        # Add note
        data.notes = f"Auto-imported from Progressive PDF on {datetime.now().strftime('%Y-%m-%d')}"

        return data

    def _extract_policy_period(self, text: str) -> Optional[dict[str, Any]]:
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

        # Find section for this VIN
        vin_pattern = rf"VIN\s+{re.escape(vin)}.*?(?=VIN\s+[A-HJ-NPR-Z0-9]{{17}}|$)"
        match = re.search(vin_pattern, text, re.IGNORECASE | re.DOTALL)

        if match:
            section = match.group(0)

            # Extract vehicle premium
            vehicle_premium = self._extract_pattern(
                section, self.PATTERNS["vehicle_premium"]
            )
            if vehicle_premium:
                data["premium_amount"] = self._parse_currency(vehicle_premium)

            # Extract deductible
            deductible = self._extract_pattern(section, self.PATTERNS["deductible"])
            if deductible:
                data["deductible"] = self._parse_currency(deductible)

        return data

    def _extract_coverage_limits(self, text: str) -> Optional[str]:
        """Extract coverage limit information."""
        pattern = r"(\$?\d{2,3},?\d{3})\s+each\s+person.*?(\$?\d{2,3},?\d{3})\s+each\s+accident.*?(\$?\d{2,3},?\d{3})\s+each\s+accident"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

        if match:
            bi_person = match.group(1).replace("$", "").replace(",", "")
            bi_accident = match.group(2).replace("$", "").replace(",", "")
            pd = match.group(3).replace("$", "").replace(",", "")
            return f"Bodily Injury: {bi_person}/{bi_accident}, Property Damage: {pd}"

        return None


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

    def parse(self, text: str, target_vin: Optional[str] = None) -> InsuranceData:
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
                    data.premium_frequency = self._determine_frequency(
                        start_date, end_date
                    )
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

        data.notes = f"Auto-imported from State Farm PDF on {datetime.now().strftime('%Y-%m-%d')}"

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

    def parse(self, text: str, target_vin: Optional[str] = None) -> InsuranceData:
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
                    data.premium_frequency = self._determine_frequency(
                        start_date, end_date
                    )
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

        data.notes = (
            f"Auto-imported from GEICO PDF on {datetime.now().strftime('%Y-%m-%d')}"
        )

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

    def parse(self, text: str, target_vin: Optional[str] = None) -> InsuranceData:
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
                    data.premium_frequency = self._determine_frequency(
                        start_date, end_date
                    )
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

        data.notes = (
            f"Auto-imported from Allstate PDF on {datetime.now().strftime('%Y-%m-%d')}"
        )

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

    def parse(self, text: str, target_vin: Optional[str] = None) -> InsuranceData:
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
                    data.premium_frequency = self._determine_frequency(
                        start_date, end_date
                    )
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

        data.notes = f"Auto-imported from PDF on {datetime.now().strftime('%Y-%m-%d')} (generic parser)"

        return data
