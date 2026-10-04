"""WMI (World Manufacturer Identifier) analysis and market region detection.

Provides standards-compliant VIN market detection and manufacturer identification
according to ISO 3779 and ISO 3780 standards.
"""

from enum import StrEnum


class MarketRegion(StrEnum):
    """Geographic market region for a vehicle based on its VIN / WMI."""

    NORTH_AMERICA = "north_america"
    EUROPE = "europe"
    OTHER = "other"


# Country code mappings for first two characters of VIN / WMI (ISO 3780)
_REGION_COUNTRIES: dict[str, str] = {
    # North America
    "1": "United States",
    "4": "United States",
    "5": "United States",
    "2": "Canada",
    "3": "Mexico",
    # Europe
    "SA": "United Kingdom",
    "SB": "United Kingdom",
    "SC": "United Kingdom",
    "SD": "United Kingdom",
    "SE": "United Kingdom",
    "SF": "United Kingdom",
    "SG": "United Kingdom",
    "SH": "United Kingdom",
    "SJ": "United Kingdom",
    "SK": "United Kingdom",
    "SL": "United Kingdom",
    "SM": "United Kingdom",
    "SN": "Germany",
    "SP": "Germany",
    "SR": "Germany",
    "SS": "Germany",
    "ST": "Germany",
    "SU": "Poland",
    "SV": "Poland",
    "SW": "Poland",
    "SX": "Poland",
    "SY": "Poland",
    "SZ": "Poland",
    "TA": "Switzerland",
    "TB": "Switzerland",
    "TC": "Switzerland",
    "TD": "Switzerland",
    "TE": "Switzerland",
    "TF": "Switzerland",
    "TG": "Switzerland",
    "TH": "Switzerland",
    "TJ": "Czech Republic",
    "TK": "Czech Republic",
    "TL": "Czech Republic",
    "TM": "Czech Republic",
    "TN": "Czech Republic",
    "TP": "Czech Republic",
    "TR": "Hungary",
    "TS": "Hungary",
    "TT": "Hungary",
    "TU": "Hungary",
    "TV": "Hungary",
    "TW": "Portugal",
    "TX": "Portugal",
    "TY": "Portugal",
    "TZ": "Portugal",
    "VA": "Austria",
    "VB": "Austria",
    "VC": "Austria",
    "VD": "Austria",
    "VE": "Austria",
    "VF": "France",
    "VG": "France",
    "VH": "France",
    "VJ": "France",
    "VK": "France",
    "VL": "France",
    "VM": "France",
    "VN": "France",
    "VP": "France",
    "VR": "France",
    "VS": "Spain",
    "VT": "Spain",
    "VU": "Spain",
    "VV": "Spain",
    "VW": "Spain",
    "WA": "Germany",
    "WB": "Germany",
    "WC": "Germany",
    "WD": "Germany",
    "WE": "Germany",
    "WF": "Germany",
    "WG": "Germany",
    "WH": "Germany",
    "WJ": "Germany",
    "WK": "Germany",
    "WL": "Germany",
    "WM": "Germany",
    "WN": "Germany",
    "WP": "Germany",
    "WR": "Germany",
    "WS": "Germany",
    "WT": "Germany",
    "WU": "Germany",
    "WV": "Germany",
    "WW": "Germany",
    "WX": "Germany",
    "WY": "Germany",
    "WZ": "Germany",
    "W0": "Germany",
    "XL": "Netherlands",
    "XM": "Netherlands",
    "XN": "Netherlands",
    "XP": "Netherlands",
    "XR": "Netherlands",
    "XS": "Russia",
    "XT": "Russia",
    "XU": "Russia",
    "XV": "Russia",
    "XW": "Russia",
    "YA": "Belgium",
    "YB": "Belgium",
    "YC": "Belgium",
    "YD": "Belgium",
    "YE": "Belgium",
    "YF": "Finland",
    "YG": "Finland",
    "YH": "Finland",
    "YJ": "Finland",
    "YK": "Finland",
    "YS": "Sweden",
    "YT": "Sweden",
    "YU": "Sweden",
    "YV": "Sweden",
    "YW": "Sweden",
    "ZA": "Italy",
    "ZB": "Italy",
    "ZC": "Italy",
    "ZD": "Italy",
    "ZE": "Italy",
    "ZF": "Italy",
    "ZG": "Italy",
    "ZH": "Italy",
    "ZJ": "Italy",
    "ZK": "Italy",
    "ZL": "Italy",
    "ZM": "Italy",
    "ZN": "Italy",
    "ZP": "Italy",
    "ZR": "Italy",
}

# Known WMI 3-character database
WMI_DATABASE: dict[str, dict[str, str]] = {
    # Germany / European Ford
    "WF0": {"make": "Ford", "manufacturer": "FORD WERKE AG", "country": "Germany"},
    "WF1": {"make": "Ford", "manufacturer": "FORD WERKE AG", "country": "Germany"},
    # BMW
    "WBA": {"make": "BMW", "manufacturer": "Bayerische Motoren Werke AG", "country": "Germany"},
    "WBS": {"make": "BMW", "manufacturer": "BMW M GmbH", "country": "Germany"},
    "WBY": {"make": "BMW", "manufacturer": "BMW i", "country": "Germany"},
    "WMW": {"make": "MINI", "manufacturer": "BMW AG / MINI", "country": "Germany"},
    # Mercedes-Benz
    "WDB": {"make": "Mercedes-Benz", "manufacturer": "Mercedes-Benz AG", "country": "Germany"},
    "WDC": {"make": "Mercedes-Benz", "manufacturer": "DaimlerChrysler AG", "country": "Germany"},
    "WDD": {"make": "Mercedes-Benz", "manufacturer": "Mercedes-Benz AG", "country": "Germany"},
    "WDF": {"make": "Mercedes-Benz", "manufacturer": "Mercedes-Benz Vans", "country": "Germany"},
    "WMX": {"make": "Mercedes-AMG", "manufacturer": "Mercedes-AMG GmbH", "country": "Germany"},
    # Volkswagen Group
    "WVW": {"make": "Volkswagen", "manufacturer": "Volkswagen AG", "country": "Germany"},
    "WVG": {"make": "Volkswagen", "manufacturer": "Volkswagen AG (SUV)", "country": "Germany"},
    "WV1": {"make": "Volkswagen", "manufacturer": "Volkswagen Commercial", "country": "Germany"},
    "WV2": {"make": "Volkswagen", "manufacturer": "Volkswagen Commercial", "country": "Germany"},
    "WAU": {"make": "Audi", "manufacturer": "Audi AG", "country": "Germany"},
    "WA1": {"make": "Audi", "manufacturer": "Audi AG (SUV)", "country": "Germany"},
    "WP0": {"make": "Porsche", "manufacturer": "Dr. Ing. h.c. F. Porsche AG", "country": "Germany"},
    "WP1": {"make": "Porsche", "manufacturer": "Porsche AG (SUV)", "country": "Germany"},
    "TMB": {"make": "Škoda", "manufacturer": "Škoda Auto a.s.", "country": "Czech Republic"},
    "VSS": {"make": "SEAT", "manufacturer": "SEAT S.A.", "country": "Spain"},
    # Italy
    "ZAR": {"make": "Alfa Romeo", "manufacturer": "Alfa Romeo Automobiles S.p.A.", "country": "Italy"},
    "ZFA": {"make": "Fiat", "manufacturer": "Fiat Chrysler Automobiles", "country": "Italy"},
    "ZFC": {"make": "Fiat", "manufacturer": "Fiat V.I.", "country": "Italy"},
    "ZFF": {"make": "Ferrari", "manufacturer": "Ferrari S.p.A.", "country": "Italy"},
    "ZAM": {"make": "Maserati", "manufacturer": "Maserati S.p.A.", "country": "Italy"},
    "ZHW": {"make": "Lamborghini", "manufacturer": "Automobili Lamborghini S.p.A.", "country": "Italy"},
    # France
    "VF1": {"make": "Renault", "manufacturer": "Renault S.A.", "country": "France"},
    "VF3": {"make": "Peugeot", "manufacturer": "Peugeot S.A.", "country": "France"},
    "VF7": {"make": "Citroën", "manufacturer": "Citroën S.A.", "country": "France"},
    "VR1": {"make": "DS Automobiles", "manufacturer": "DS Automobiles", "country": "France"},
    "VR3": {"make": "Peugeot", "manufacturer": "Peugeot S.A.", "country": "France"},
    # United Kingdom
    "SAJ": {"make": "Jaguar", "manufacturer": "Jaguar Land Rover Ltd", "country": "United Kingdom"},
    "SAL": {"make": "Land Rover", "manufacturer": "Jaguar Land Rover Ltd", "country": "United Kingdom"},
    "SAR": {"make": "Rover", "manufacturer": "Rover Group", "country": "United Kingdom"},
    "SCC": {"make": "Lotus", "manufacturer": "Lotus Cars Ltd", "country": "United Kingdom"},
    "SHS": {"make": "Honda", "manufacturer": "Honda UK Manufacturing Ltd", "country": "United Kingdom"},
    # Sweden
    "YV1": {"make": "Volvo", "manufacturer": "Volvo Car Corporation", "country": "Sweden"},
    "YV2": {"make": "Volvo", "manufacturer": "Volvo Trucks", "country": "Sweden"},
    "YS3": {"make": "Saab", "manufacturer": "Saab Automobile AB", "country": "Sweden"},
    # North America - USA
    "1FA": {"make": "Ford", "manufacturer": "Ford Motor Company", "country": "United States"},
    "1FB": {"make": "Ford", "manufacturer": "Ford Motor Company", "country": "United States"},
    "1FC": {"make": "Ford", "manufacturer": "Ford Motor Company", "country": "United States"},
    "1FD": {"make": "Ford", "manufacturer": "Ford Motor Company", "country": "United States"},
    "1FM": {"make": "Ford", "manufacturer": "Ford Motor Company", "country": "United States"},
    "1FT": {"make": "Ford", "manufacturer": "Ford Motor Company", "country": "United States"},
    "1G1": {"make": "Chevrolet", "manufacturer": "General Motors", "country": "United States"},
    "1GC": {"make": "Chevrolet", "manufacturer": "General Motors", "country": "United States"},
    "1HD": {"make": "Harley-Davidson", "manufacturer": "Harley-Davidson", "country": "United States"},
    "1HG": {"make": "Honda", "manufacturer": "Honda of America Mfg.", "country": "United States"},
    "1J4": {"make": "Jeep", "manufacturer": "FCA US LLC", "country": "United States"},
    "1C4": {"make": "Chrysler", "manufacturer": "FCA US LLC", "country": "United States"},
    "4T1": {"make": "Toyota", "manufacturer": "Toyota Motor Manufacturing USA", "country": "United States"},
    "5YJ": {"make": "Tesla", "manufacturer": "Tesla, Inc.", "country": "United States"},
    "7SA": {"make": "Tesla", "manufacturer": "Tesla, Inc.", "country": "United States"},
    # North America - Canada
    "2FA": {"make": "Ford", "manufacturer": "Ford Motor Company of Canada", "country": "Canada"},
    "2G1": {"make": "Chevrolet", "manufacturer": "General Motors of Canada", "country": "Canada"},
    "2HG": {"make": "Honda", "manufacturer": "Honda of Canada Mfg.", "country": "Canada"},
    "2T1": {"make": "Toyota", "manufacturer": "Toyota Motor Manufacturing Canada", "country": "Canada"},
    "2T2": {"make": "Lexus", "manufacturer": "Toyota Motor Manufacturing Canada", "country": "Canada"},
    # North America - Mexico
    "3FA": {"make": "Ford", "manufacturer": "Ford Motor Company Mexico", "country": "Mexico"},
    "3FT": {"make": "Ford", "manufacturer": "Ford Motor Company Mexico", "country": "Mexico"},
    "3G1": {"make": "Chevrolet", "manufacturer": "General Motors de Mexico", "country": "Mexico"},
    "3VW": {"make": "Volkswagen", "manufacturer": "Volkswagen de Mexico", "country": "Mexico"},
}


def get_wmi(vin: str) -> str:
    """
    Extract the 3-character World Manufacturer Identifier (WMI) from a VIN.

    Args:
        vin: 17-character VIN string

    Returns:
        3-character uppercase WMI string (or shorter if len < 3)
    """
    cleaned = vin.strip().upper()
    return cleaned[:3]


def detect_market_region(vin: str) -> MarketRegion:
    """
    Determine the vehicle's market region based on the first character of its VIN / WMI.

    Rules:
    - North American Market:
      VIN starts with 1, 4, 5 (United States), 2 (Canada), or 3 (Mexico).
    - European Market:
      VIN starts with letters between 'S' and 'Z' (inclusive),
      e.g., W=Germany, Z=Italy, V=France/Spain, S=United Kingdom, T=Switzerland/Czechia, etc.
    - Other Markets:
      Any other starting character (Asia, Oceania, South America, Africa).

    Args:
        vin: Vehicle Identification Number

    Returns:
        MarketRegion enum value
    """
    cleaned = vin.strip().upper()
    if not cleaned:
        return MarketRegion.OTHER

    first_char = cleaned[0]

    # North America: 1, 4, 5 (USA), 2 (Canada), 3 (Mexico)
    if first_char in ("1", "2", "3", "4", "5"):
        return MarketRegion.NORTH_AMERICA

    # Europe: S through Z
    if "S" <= first_char <= "Z":
        return MarketRegion.EUROPE

    return MarketRegion.OTHER


def lookup_wmi(vin_or_wmi: str) -> dict[str, str] | None:
    """
    Lookup manufacturer brand, full manufacturer name, and origin country for a WMI.

    Args:
        vin_or_wmi: Either a full 17-character VIN or a 3-character WMI

    Returns:
        Dictionary with keys 'make', 'manufacturer', 'country' or None if unknown
    """
    wmi = get_wmi(vin_or_wmi)
    if not wmi:
        return None

    # Check exact 3-char match
    if wmi in WMI_DATABASE:
        return WMI_DATABASE[wmi].copy()

    # Fall back to 2-char country lookup
    two_char = wmi[:2]
    first_char = wmi[:1]
    country = _REGION_COUNTRIES.get(two_char) or _REGION_COUNTRIES.get(first_char)

    if country:
        return {"make": "", "manufacturer": "", "country": country}

    return None
