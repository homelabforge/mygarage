"""The French motor insurance document parser (#211).

An avis d'échéance, a certificat d'assurance, a tableau de garanties or the
conditions particulières of a French contract print the same things in the
same words: the insurer, the n° de contrat, the période du … au … or the
échéance, the cotisation, the franchise, the formule (au tiers, tiers étendu,
tous risques), the coefficient de réduction-majoration (bonus-malus) and the
immatriculation. Rarely the VIN, which is why `plates_found` exists.

Every amount goes through the same reader as the carte grise
(`registration.to_decimal`: « 612,40 € », « 1 234,56 »), every date through
`registration.iso_date` (« 15/03/2026 », « 15.03.2026 ») or the month names
below (« 1er mars 2026 »). The standard coverages are read off the page by
the catalogue (`app.utils.insurance_coverages`), whose French phrases are
what make « Bris de glace : franchise 80 € » a `glass` row.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.constants.insurance import clean_no_claims_class

from .insurance import InsuranceData, InsuranceDocumentParser, classify_formula, plates_in
from .registration import iso_date, to_decimal

#: Insurers whose name identifies the document, longest first so « Direct
#: Assurance » is read before a bare « Assurance » would be.
KNOWN_INSURERS: tuple[str, ...] = (
    "Direct Assurance",
    "Crédit Agricole Assurances",
    "Crédit Mutuel",
    "Banque Populaire",
    "Caisse d'Epargne",
    "Assurances du Crédit Mutuel",
    "Mutuelle de Poitiers",
    "La Banque Postale",
    "Société Générale",
    "Abeille Assurances",
    "Thélem Assurances",
    "Groupama",
    "Pacifica",
    "Generali",
    "Allianz",
    "Eurofil",
    "L'olivier",
    "Leocare",
    "Ornikar",
    "Matmut",
    "Covéa",
    "MAIF",
    "MACIF",
    "MAAF",
    "AXA",
    "GMF",
    "Luko",
    "Lovys",
    "Flitter",
    "Acheel",
    "Olivier",
    "Amaguiz",
    "Assu 2000",
    "Euro-Assurance",
    "Aviva",
    "Swiss Life",
    "April",
    "Hiscox",
    "Mondial Assistance",
    "Wakam",
)

#: « janvier », « févr. », « 1er mars 2026 »…
_MONTHS: dict[str, int] = {
    "janvier": 1,
    "janv": 1,
    "février": 2,
    "fevrier": 2,
    "févr": 2,
    "fevr": 2,
    "mars": 3,
    "avril": 4,
    "avr": 4,
    "mai": 5,
    "juin": 6,
    "juillet": 7,
    "juil": 7,
    "août": 8,
    "aout": 8,
    "septembre": 9,
    "sept": 9,
    "octobre": 10,
    "oct": 10,
    "novembre": 11,
    "nov": 11,
    "décembre": 12,
    "decembre": 12,
    "déc": 12,
    "dec": 12,
}
_MONTH_WORDS = "|".join(sorted(_MONTHS, key=len, reverse=True))
#: A printed date in either shape.
_DATE = (
    rf"(?:\d{{1,2}}[/.\-]\d{{1,2}}[/.\-]\d{{4}}|\d{{1,2}}(?:er)?\s+(?:{_MONTH_WORDS})\.?\s+\d{{4}})"
)
_DATE_RE = re.compile(_DATE, re.IGNORECASE)
_WORDED_DATE_RE = re.compile(
    rf"(\d{{1,2}})(?:er)?\s+({_MONTH_WORDS})\.?\s+(\d{{4}})", re.IGNORECASE
)
#: « 612,40 », « 1 234,56 », « 1.234,56 », « 300 ».
_AMOUNT = r"(\d{1,3}(?:[   .]\d{3})*(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)"

_PERIOD_PATTERNS: tuple[str, ...] = (
    rf"du\s+({_DATE})\s+au\s+({_DATE})",
    rf"(?:période|periode)\s+(?:de\s+)?(?:garantie|validité|validite|couverture|d['’]assurance|du\s+contrat)"
    rf"\s*[:\-–]?\s*(?:du\s+)?({_DATE})\s*(?:au|-|–|à)\s*({_DATE})",
    rf"({_DATE})\s*(?:-|–|au)\s*({_DATE})",
)
_DUE_DATE_PATTERNS: tuple[str, ...] = (
    rf"(?:date\s+d['’]?[ée]ch[ée]ance|[ée]ch[ée]ance\s+(?:principale|annuelle|du\s+contrat)?|prochaine\s+[ée]ch[ée]ance)"
    rf"\s*[:\-–]?\s*(?:le\s+)?({_DATE})",
)
_EFFECT_DATE_PATTERNS: tuple[str, ...] = (
    rf"(?:date\s+d['’]effet|prise\s+d['’]effet|effet\s+(?:du\s+contrat|des\s+garanties)|à\s+effet\s+du)"
    rf"\s*[:\-–]?\s*(?:le\s+)?({_DATE})",
)
_POLICY_NUMBER_PATTERNS: tuple[str, ...] = (
    r"(?:n[°ºo]\.?|num[ée]ro)\s*(?:de\s+|du\s+)?(?:contrat|police|soci[ée]taire|adh[ée]sion|dossier)"
    r"\s*[:\-–]?\s*([A-Z0-9][A-Z0-9 \-/.]{3,30}?)(?=\s*(?:\n|$|[,;]|\s{2,}|\s+(?:du|au|le|[ée]ch|formule|date|p[ée]riode)\b))",
    r"(?:contrat|police)\s*(?:n[°ºo]\.?|num[ée]ro)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9\-/.]{3,30})",
    r"r[ée]f[ée]rence\s+(?:du\s+|de\s+)?(?:contrat|police)\s*[:\-–]?\s*([A-Z0-9][A-Z0-9\-/.]{3,30})",
)
_PREMIUM_PATTERNS: tuple[str, ...] = (
    rf"(?:cotisation|prime)\s+(?:totale|annuelle|globale|nette|ttc|t\.t\.c\.|à\s+payer|a\s+payer|due)?"
    rf"(?:\s+(?:ttc|t\.t\.c\.|annuelle|totale))?\s*[:\-–]?\s*{_AMOUNT}\s*(?:€|eur)",
    rf"(?:total\s+(?:ttc|t\.t\.c\.|à\s+payer|a\s+payer|de\s+la\s+cotisation)|montant\s+(?:total|de\s+la\s+cotisation|à\s+payer|a\s+payer))"
    rf"\s*[:\-–]?\s*{_AMOUNT}\s*(?:€|eur)",
    rf"(?:cotisation|prime)[^\n€]{{0,40}}?{_AMOUNT}\s*(?:€|eur)",
)
_DEDUCTIBLE_PATTERNS: tuple[str, ...] = (
    # A line of its own first (« Franchise : 300 € »), then the first
    # priced franchise anywhere (a coverage's own).
    rf"^[ \t]*franchise(?:\s+(?:générale|generale|de\s+base|contractuelle))?\s*[:\-–]?\s*{_AMOUNT}\s*(?:€|eur)",
    rf"franchise[^\n€]{{0,40}}?{_AMOUNT}\s*(?:€|eur)",
)
_NO_CLAIMS_PATTERNS: tuple[str, ...] = (
    r"(?:coefficient\s+(?:de\s+)?(?:r[ée]duction[- ]majoration|bonus[- ]malus)|bonus[- ]malus|c\.?r\.?m\.?|coefficient)"
    r"(?:\s*\([^)\n]{0,30}\))?\s*[:\-–]?\s*(?:de\s+|actuel\s*[:\-–]?\s*)?([0-3][.,]\d{2})\b",
)
_FREQUENCY_WORDS: tuple[tuple[str, str], ...] = (
    (r"mensuel|mensualit|par\s+mois|/\s*mois", "Monthly"),
    (r"trimestriel|par\s+trimestre", "Quarterly"),
    (r"semestriel|par\s+semestre", "Semi-Annual"),
    (r"annuel|par\s+an\b|/\s*an\b", "Annual"),
)
#: What makes a page a French motor insurance document: at least three of
#: these groups, so a Progressive page (no euro, no French) and a carte grise
#: (no cotisation, no formule) are not read as one.
_MARKER_GROUPS: tuple[str, ...] = (
    r"\bassureur\b|\bassurances?\b|\bassur[ée]e?\b|\bsoci[ée]taire\b",
    r"n[°ºo]\.?\s*(?:de\s+)?(?:contrat|police|soci[ée]taire)|num[ée]ro\s+(?:de\s+)?(?:contrat|police)|contrat\s+n[°ºo]",
    r"[ée]ch[ée]ance|date\s+d['’]effet|p[ée]riode\s+(?:de\s+)?(?:garantie|validit[ée]|couverture)|\bdu\s+\d{1,2}/\d{1,2}/\d{4}\s+au\b",
    r"\bcotisation\b|\bprime\b",
    r"\bfranchise\b",
    r"responsabilit[ée]\s+civile",
    r"tous\s+risques|au\s+tiers|tiers\s+[ée]tendu|formule",
    r"€|\beuros?\b",
    r"\bimmatriculation\b|\bv[ée]hicule\s+assur[ée]\b|\bconducteur\b",
)


def fr_date(value: str | None) -> str | None:
    """ISO date from « 15/03/2026 », « 15.03.2026 » or « 1er mars 2026 »."""
    if not value:
        return None
    worded = _WORDED_DATE_RE.search(value)
    if worded:
        day, month_word, year = worded.groups()
        month = _MONTHS.get(month_word.lower().rstrip("."))
        if month is None:
            return None
        try:
            return date(int(year), month, int(day)).isoformat()
        except ValueError:
            return None
    return iso_date(value)


def _shift_year(iso: str, years: int) -> str:
    """The same day `years` later (or earlier); 29 February lands on the 28th."""
    parsed = datetime.strptime(iso, "%Y-%m-%d").date()
    try:
        return parsed.replace(year=parsed.year + years).isoformat()
    except ValueError:
        return (parsed.replace(day=28, year=parsed.year + years)).isoformat()


class FrenchInsuranceParser(InsuranceDocumentParser):
    """Parser for French motor insurance documents, whatever the insurer."""

    PARSER_NAME = "FrenchInsurance"
    PROVIDER_NAME = "Unknown"

    def can_parse(self, text: str) -> bool:
        lowered = text.lower()
        hits = sum(1 for pattern in _MARKER_GROUPS if re.search(pattern, lowered, re.IGNORECASE))
        return hits >= 3

    def parse(self, text: str, *, target_vin: str | None = None, **kwargs: Any) -> InsuranceData:
        data = InsuranceData(parser_name=self.PARSER_NAME, raw_text=text)

        data.provider = self._insurer(text)
        data.field_confidence["provider"] = "high" if data.provider != "Unknown" else "low"

        number = self._extract_pattern(text, list(_POLICY_NUMBER_PATTERNS))
        if number:
            data.policy_number = number.strip(" -/.")[:50]
            data.field_confidence["policy_number"] = "high"

        start, end, dates_confidence = self._period(text)
        if start and end:
            data.start_date, data.end_date = start, end
            data.field_confidence["dates"] = dates_confidence

        premium, premium_line = self._premium(text)
        if premium is not None:
            data.premium_amount = premium
            data.field_confidence["premium_amount"] = "high"
        data.premium_frequency = self._frequency(premium_line, text, data.start_date, data.end_date)

        # The first priced franchise is the headline deductible; « sans
        # franchise » and « franchise : néant » price nothing.
        deductible = self._extract_pattern(text, list(_DEDUCTIBLE_PATTERNS))
        amount = to_decimal(deductible) if deductible else None
        if amount is not None and amount > 0:
            data.deductible = amount
            data.field_confidence["deductible"] = "medium"

        data.policy_type = classify_formula(text) or "Other"
        if data.policy_type != "Other":
            data.field_confidence["policy_type"] = "high"

        no_claims = self._extract_pattern(text, list(_NO_CLAIMS_PATTERNS))
        data.no_claims_class = clean_no_claims_class(no_claims) if no_claims else None
        if data.no_claims_class:
            data.field_confidence["no_claims_class"] = "high"

        data.vehicles_found = self._extract_all_vins(text)
        data.plates_found = plates_in(text)
        if target_vin:
            data.extracted_vin = target_vin.upper()

        data.confidence_score = self._calculate_confidence(data)
        data.notes = f"Auto-imported from a French policy document on {date.today().isoformat()}"
        return data

    # ------------------------------------------------------------------ parts

    @staticmethod
    def _insurer(text: str) -> str:
        labelled = re.search(
            r"(?:assureur|compagnie|soci[ée]t[ée]\s+d['’]assurance)\s*[:\-–]\s*([^\n]{2,60})",
            text,
            re.IGNORECASE,
        )
        # The labelled name first; else the known insurer printed FIRST on
        # the page (the header), not the first of the list: a MAAF notice
        # names Covéa, its group, further down.
        for candidate in ([labelled.group(1)] if labelled else []) + [text]:
            found: list[tuple[int, str]] = []
            for insurer in KNOWN_INSURERS:
                match = re.search(
                    rf"(?<![A-Za-z]){re.escape(insurer)}(?![A-Za-z])", candidate, re.I
                )
                if match:
                    found.append((match.start(), insurer))
            if found:
                return min(found)[1]
        if labelled:
            return " ".join(labelled.group(1).split())[:100]
        return "Unknown"

    @staticmethod
    def _period(text: str) -> tuple[str | None, str | None, str]:
        for pattern in _PERIOD_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start, end = fr_date(match.group(1)), fr_date(match.group(2))
                if start and end and end > start:
                    return start, end, "high"
        for pattern in _DUE_DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                end = fr_date(match.group(1))
                if end:
                    # An échéance is the end of a yearly term.
                    return _shift_year(end, -1), end, "medium"
        for pattern in _EFFECT_DATE_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                start = fr_date(match.group(1))
                if start:
                    return start, _shift_year(start, 1), "medium"
        return None, None, "low"

    @staticmethod
    def _premium(text: str) -> tuple[Decimal | None, str]:
        for pattern in _PREMIUM_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount = to_decimal(match.group(1))
                if amount is not None and amount > 0:
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    return amount, text[line_start : line_end if line_end != -1 else None]
        return None, ""

    @staticmethod
    def _frequency(premium_line: str, text: str, start: str | None, end: str | None) -> str | None:
        for scope in (premium_line, text):
            lowered = scope.lower()
            for pattern, frequency in _FREQUENCY_WORDS:
                if re.search(pattern, lowered):
                    return frequency
        if start and end:
            return InsuranceDocumentParser._determine_frequency(start, end)
        return None
