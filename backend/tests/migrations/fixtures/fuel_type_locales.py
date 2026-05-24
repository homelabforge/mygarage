"""Locale-aware free-text → canonical fuel-type fixtures.

What this catches
-----------------
The rc1 migration 054 backfill normalizes free-text ``fuel_type`` values
to a canonical enum. Its ``_NORMALIZATION_MAP`` is English-only. When a
Polish-locale user with vehicle ``fuel_type='Benzyna'`` (Polish for
gasoline/petrol) ran the migration, the value silently mapped to
``other`` instead of ``gasoline``. MyGarage ships in en/pl/uk/ru, so
backfill vocabularies need locale-aware coverage.

This fixture is the truth table the parametrized backfill test
iterates over. Phase 1.3 expands ``_NORMALIZATION_MAP`` in migration
054 with these entries; the test then goes green.

Adding a new locale
-------------------
Add an entry to ``LOCALE_FIXTURES`` keyed by locale code. Provide as
many free-text values as the locale's actual users tend to type. Test
parametrization will generate one assertion per (locale, free_text)
pair.

Notes on data
-------------
- Polish/Ukrainian/Russian entries below are the most common terms a
  user adding a vehicle in those languages would type — verified
  against the catalogs MyGarage's i18n maintainers reference.
- LPG (autogas) is hugely popular in Poland; the Polish entry list
  reflects that.
- Strings include both lowercase and TitleCase forms because users
  type both. The migration's normalization lowercases before lookup,
  so the map only needs lowercase keys.
"""

from __future__ import annotations

# locale → { free_text_input_user_typed: expected_canonical_enum_value }
LOCALE_FIXTURES: dict[str, dict[str, str]] = {
    "en": {
        # Sanity — these already pass on rc1; confirms the harness is wired.
        "Gasoline": "gasoline",
        "gas": "gasoline",
        "Diesel": "diesel",
        "Premium": "gasoline",
        "Electric": "electric",
        "Hybrid": "hybrid",
        "PHEV": "plugin_hybrid",
        "E85": "e85",
        "LPG": "propane_lpg",
        "CNG": "cng",
    },
    "pl": {
        # Polish — andrzejf1994's locale, the report origin.
        "Benzyna": "gasoline",
        "benzyna": "gasoline",
        "Olej napędowy": "diesel",
        "Diesel": "diesel",  # English loanword, common in PL too
        "Gaz": "propane_lpg",  # Common Polish term for LPG/autogas
        "LPG": "propane_lpg",
        "Elektryczny": "electric",
        "Hybryda": "hybrid",
        "Hybrydowy": "hybrid",
    },
    "uk": {
        # Ukrainian
        "Бензин": "gasoline",
        "Дизель": "diesel",
        "Газ": "propane_lpg",
        "Електричний": "electric",
        "Гібрид": "hybrid",
    },
    "ru": {
        # Russian
        "Бензин": "gasoline",
        "Дизель": "diesel",
        "Газ": "propane_lpg",
        "Электрический": "electric",
        "Гибрид": "hybrid",
    },
}


def all_pairs() -> list[tuple[str, str, str]]:
    """Flatten LOCALE_FIXTURES into ``(locale, free_text, expected)`` tuples
    for ``pytest.mark.parametrize`` consumption."""
    return [
        (locale, free_text, expected)
        for locale, mapping in LOCALE_FIXTURES.items()
        for free_text, expected in mapping.items()
    ]
