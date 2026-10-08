"""Insurance vocabularies shared by the model, the schemas and the profiles.

``POLICY_TYPE_VALUES`` is what ``insurance_policy_vehicles.policy_type`` may
hold. The first six are the North American formulas the app started with;
``Third Party`` and ``Third Party Extended`` are the European ones (#211):
« au tiers » / « tiers étendu », Haftpflicht / Teilkasko, RC auto / kasko
parziale, a terceros / terceros ampliado. « Tous risques », Vollkasko and
todo riesgo are ``Full Coverage``, which already existed.

No CHECK constraint carries this list any more (migration 149 dropped it,
the way 146 did for tax types): the schemas refuse a value outside it on
every write path, and a stored value is read as it is.
"""

from __future__ import annotations

import re

POLICY_TYPE_VALUES: tuple[str, ...] = (
    "Liability",
    "Comprehensive",
    "Collision",
    "Full Coverage",
    "Minimum",
    "Other",
    "Third Party",
    "Third Party Extended",
)

#: The formulas a European country profile lists, in the order a form shows
#: them; ``app/data/country_profiles/*.json`` must stay inside this set.
EU_POLICY_TYPES: tuple[str, ...] = ("Third Party", "Third Party Extended", "Full Coverage", "Other")

#: ``insurance_policy_vehicles.no_claims_class``: a bonus-malus coefficient
#: (« 0.50 »), a Schadenfreiheitsklasse (« SF 12 »), a classe di merito
#: (« 1 »), a percentage (« 50 % »)… Ten characters of plain text; the
#: country profile's ``insurance.no_claims.pattern`` is a hint for the form,
#: never a rule the API enforces, since the schemes differ per insurer.
NO_CLAIMS_CLASS_PATTERN = r"^[A-Za-z0-9 .,/%-]{1,10}$"
NO_CLAIMS_CLASS_RE = re.compile(NO_CLAIMS_CLASS_PATTERN)


def clean_no_claims_class(value: object) -> str | None:
    """``value`` trimmed, with a French decimal comma read as a point, or None
    when it is not a short plain-text class (« 0,50 » → « 0.50 »)."""
    if not isinstance(value, str):
        return None
    printed = " ".join(value.split())
    if re.fullmatch(r"[0-3],\d{2}", printed):
        printed = printed.replace(",", ".")
    return printed if NO_CLAIMS_CLASS_RE.fullmatch(printed) else None
