"""Insurance PDF parser service for extracting policy data from PDFs.

DEPRECATED: This module is deprecated as of v2.4.0.
Use app.services.document_ocr.document_ocr_service instead, which provides:
- Unified OCR architecture (same as window stickers)
- Multi-provider support (Progressive, State Farm, GEICO, Allstate)
- Auto-detection of insurance providers
- Image file support (JPG, PNG) in addition to PDF
- Better confidence scoring

This file is kept for backwards compatibility but will be removed in a future version.
"""

import warnings
import pdfplumber
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Dict, Any
from io import BytesIO
import logging

logger = logging.getLogger(__name__)

warnings.warn(
    "insurance_pdf_parser is deprecated, use document_ocr_service instead",
    DeprecationWarning,
    stacklevel=2
)


class InsurancePDFParser:
    """Parse insurance policy PDFs to extract structured data."""

    def __init__(self):
        self.progressive_patterns = {
            'policy_number': [
                r'Auto\s+(\d+)',
                r'Policy\s+(?:Number|#):\s*(\d+)',
                r'Policy:\s*Auto\s+(\d+)',
            ],
            'policy_period': [
                r'Policy period\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})\s*[–-]\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})',
                r'(\d{1,2}/\d{1,2}/\d{4})\s*[–-]\s*(\d{1,2}/\d{1,2}/\d{4})',
            ],
            'total_premium': [
                r'Total\s+policy\s+premium\s*\$?([\d,]+\.?\d*)',
                r'Total\s+premium\s*:?\s*\$?([\d,]+\.?\d*)',
            ],
            'vin': [
                r'VIN\s+([A-HJ-NPR-Z0-9]{17})',
                r'VIN:\s*([A-HJ-NPR-Z0-9]{17})',
            ],
            'vehicle_premium': [
                r'Total\s+vehicle\s+[Pp]remium\s*\$?([\d,]+\.?\d*)',
            ],
            'deductible': [
                r'\$(\d+)\s+[Dd]eductible',
                r'(\d+)\s+deductible',
            ],
            'provider': [
                r'(Progressive|State Farm|Geico|Allstate|Farmers)',
            ],
        }

    async def parse_progressive_pdf(self, pdf_bytes: bytes, target_vin: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse a Progressive insurance PDF.

        Args:
            pdf_bytes: PDF file content as bytes
            target_vin: Optional VIN to extract specific vehicle data

        Returns:
            Dictionary with extracted insurance data
        """
        result = {
            'provider': 'Progressive',
            'policy_number': None,
            'start_date': None,
            'end_date': None,
            'premium_amount': None,
            'premium_frequency': None,
            'deductible': None,
            'coverage_limits': None,
            'policy_type': None,
            'notes': None,
            'confidence': {},  # Confidence scores for each field
            'raw_text': '',
            'vehicles_found': [],
        }

        try:
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                full_text = ""

                # Extract text from all pages
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"

                result['raw_text'] = full_text

                # Extract policy number
                policy_num = self._extract_pattern(full_text, self.progressive_patterns['policy_number'])
                if policy_num:
                    result['policy_number'] = policy_num
                    result['confidence']['policy_number'] = 'high'

                # Extract policy period (start and end dates)
                period_match = self._extract_policy_period(full_text)
                if period_match:
                    result['start_date'] = period_match['start']
                    result['end_date'] = period_match['end']
                    result['confidence']['dates'] = 'high'

                # Extract total premium
                premium = self._extract_pattern(full_text, self.progressive_patterns['total_premium'])
                if premium:
                    result['premium_amount'] = self._parse_currency(premium)
                    result['confidence']['premium_amount'] = 'high'

                # Extract VINs and vehicle-specific data
                vins = self._extract_all_vins(full_text)
                result['vehicles_found'] = vins

                # If target VIN specified, extract vehicle-specific data
                if target_vin and target_vin in vins:
                    vehicle_data = self._extract_vehicle_specific_data(full_text, target_vin)
                    if vehicle_data:
                        result.update(vehicle_data)

                # Determine policy frequency from period
                if result['start_date'] and result['end_date']:
                    result['premium_frequency'] = self._determine_frequency(
                        result['start_date'],
                        result['end_date']
                    )

                # Determine policy type from coverage information
                result['policy_type'] = self._determine_policy_type(full_text)

                # Extract deductible
                deductible = self._extract_pattern(full_text, self.progressive_patterns['deductible'])
                if deductible:
                    result['deductible'] = self._parse_currency(deductible)
                    result['confidence']['deductible'] = 'medium'

                # Extract coverage limits
                coverage = self._extract_coverage_limits(full_text)
                if coverage:
                    result['coverage_limits'] = coverage
                    result['confidence']['coverage_limits'] = 'medium'

                # Add parsing note
                result['notes'] = f"Auto-imported from Progressive PDF on {datetime.now().strftime('%Y-%m-%d')}"

        except Exception as e:
            logger.error("Error parsing Progressive PDF: %s", e)
            raise ValueError(f"Failed to parse PDF: {str(e)}")

        return result

    def _extract_pattern(self, text: str, patterns: list) -> Optional[str]:
        """Extract first match from list of regex patterns."""
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_policy_period(self, text: str) -> Optional[Dict[str, str]]:
        """Extract and parse policy period dates."""
        for pattern in self.progressive_patterns['policy_period']:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start_str = match.group(1)
                end_str = match.group(2)

                # Parse dates
                start_date = self._parse_date(start_str)
                end_date = self._parse_date(end_str)

                if start_date and end_date:
                    return {
                        'start': start_date,
                        'end': end_date,
                    }
        return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse various date formats to YYYY-MM-DD."""
        date_formats = [
            '%B %d, %Y',  # August 26, 2025
            '%m/%d/%Y',   # 08/26/2025
            '%Y-%m-%d',   # 2025-08-26
        ]

        for fmt in date_formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        return None

    def _parse_currency(self, value: str) -> Optional[Decimal]:
        """Parse currency string to Decimal."""
        try:
            # Remove $ and commas
            cleaned = value.replace('$', '').replace(',', '').strip()
            return Decimal(cleaned)
        except (ValueError, InvalidOperation) as e:
            logger.debug("Failed to parse currency value '%s': %s", value, e)
            return None

    def _extract_all_vins(self, text: str) -> list:
        """Extract all VINs found in the PDF."""
        vins = []
        for pattern in self.progressive_patterns['vin']:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                vin = match.group(1).upper()
                if vin not in vins:
                    vins.append(vin)
        return vins

    def _extract_vehicle_specific_data(self, text: str, vin: str) -> Dict[str, Any]:
        """Extract vehicle-specific premium and deductible."""
        data = {}

        # Find the section for this VIN
        vin_pattern = rf'VIN\s+{re.escape(vin)}.*?(?=VIN\s+[A-HJ-NPR-Z0-9]{{17}}|$)'
        match = re.search(vin_pattern, text, re.IGNORECASE | re.DOTALL)

        if match:
            section = match.group(0)

            # Extract vehicle premium from this section
            vehicle_premium = self._extract_pattern(section, self.progressive_patterns['vehicle_premium'])
            if vehicle_premium:
                data['premium_amount'] = self._parse_currency(vehicle_premium)
                data['confidence'] = data.get('confidence', {})
                data['confidence']['premium_amount'] = 'high'

            # Extract deductible from this section
            deductible = self._extract_pattern(section, self.progressive_patterns['deductible'])
            if deductible:
                data['deductible'] = self._parse_currency(deductible)
                data['confidence'] = data.get('confidence', {})
                data['confidence']['deductible'] = 'medium'

        return data

    def _determine_frequency(self, start_date: str, end_date: str) -> str:
        """Determine payment frequency from policy period."""
        try:
            start = datetime.strptime(start_date, '%Y-%m-%d')
            end = datetime.strptime(end_date, '%Y-%m-%d')
            months = (end.year - start.year) * 12 + end.month - start.month

            if 5 <= months <= 7:
                return 'Semi-Annual'
            elif 11 <= months <= 13:
                return 'Annual'
            elif 2 <= months <= 4:
                return 'Quarterly'
            else:
                return 'Monthly'
        except (ValueError, AttributeError) as e:
            logger.debug("Failed to determine frequency from dates %s to %s: %s", start_date, end_date, e)
            return 'Semi-Annual'  # Progressive default

    def _determine_policy_type(self, text: str) -> str:
        """Determine policy type from coverage information."""
        text_lower = text.lower()

        # Check for Full Coverage indicators
        if all(coverage in text_lower for coverage in ['comprehensive', 'collision', 'liability']):
            return 'Full Coverage'
        elif 'comprehensive' in text_lower and 'collision' in text_lower:
            return 'Full Coverage'
        elif 'comprehensive' in text_lower:
            return 'Comprehensive'
        elif 'collision' in text_lower:
            return 'Collision'
        elif 'liability' in text_lower:
            return 'Liability'
        else:
            return 'Other'

    def _extract_coverage_limits(self, text: str) -> Optional[str]:
        """Extract coverage limit information."""
        # Look for liability limits pattern (e.g., 100/300/100)
        pattern = r'(\$?\d{2,3},?\d{3})\s+each\s+person.*?(\$?\d{2,3},?\d{3})\s+each\s+accident.*?(\$?\d{2,3},?\d{3})\s+each\s+accident'
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

        if match:
            bodily_injury_per_person = match.group(1).replace('$', '').replace(',', '')
            bodily_injury_per_accident = match.group(2).replace('$', '').replace(',', '')
            property_damage = match.group(3).replace('$', '').replace(',', '')

            return f"Bodily Injury: {bodily_injury_per_person}/{bodily_injury_per_accident}, Property Damage: {property_damage}"

        return None


# Singleton instance
insurance_pdf_parser = InsurancePDFParser()
