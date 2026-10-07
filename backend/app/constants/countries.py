"""Country vocabularies: ISO 3166-1 alpha-2 codes and the EU member states.

``country`` on a user, ``registration_country`` on a vehicle and the
``default_country`` setting all hold one of these codes (uppercase, two
letters). They are validated by Pydantic, never by a DB CHECK, like every
other vocabulary in this codebase. The frontend mirrors the list in
``src/constants/countries.ts`` and shows each country's name through
``Intl.DisplayNames``, so nothing here is translated.
"""

from __future__ import annotations

# The 249 officially assigned ISO 3166-1 alpha-2 codes (ISO 3166 Maintenance
# Agency, status "officially assigned"). Exceptional reservations such as
# "XK" (Kosovo) and "UK" are deliberately absent: Intl.DisplayNames has no
# name for most of them.
ISO_3166_ALPHA2: frozenset[str] = frozenset(
    """
    AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ
    BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
    CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ
    DE DJ DK DM DO DZ
    EC EE EG EH ER ES ET
    FI FJ FK FM FO FR
    GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY
    HK HM HN HR HT HU
    ID IE IL IM IN IO IQ IR IS IT
    JE JM JO JP
    KE KG KH KI KM KN KP KR KW KY KZ
    LA LB LC LI LK LR LS LT LU LV LY
    MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
    NA NC NE NF NG NI NL NO NP NR NU NZ
    OM
    PA PE PF PG PH PK PL PM PN PR PS PT PW PY
    QA
    RE RO RS RU RW
    SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
    TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ
    UA UG UM US UY UZ
    VA VC VE VG VI VN VU
    WF WS
    YE YT
    ZA ZM ZW
    """.split()
)

# The 27 member states of the European Union. A member state with no profile
# file of its own resolves to the ``EU`` baseline profile (EU law harmonises
# the registration certificate, fuel labels and the minimum roadworthiness
# cadence), so the app has sensible defaults there without anyone having
# written a national profile yet.
EU_MEMBER_STATES: frozenset[str] = frozenset(
    """
    AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE
    """.split()
)


#: The instance setting read when neither the vehicle nor its owner has a country.
DEFAULT_COUNTRY_SETTING_KEY = "default_country"


def is_country_code(value: str | None) -> bool:
    """True for an uppercase, officially assigned ISO 3166-1 alpha-2 code."""
    return isinstance(value, str) and value in ISO_3166_ALPHA2


def normalize_country_code(value: str | None) -> str | None:
    """Trim and uppercase a code; ``None`` or blank stays ``None``.

    Validation is the caller's job (``is_country_code``): this only makes
    ``"fr"`` and ``" FR "`` read as ``"FR"`` before it is checked.
    """
    if value is None:
        return None
    cleaned = value.strip().upper()
    return cleaned or None
