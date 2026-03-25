"""Internationalization constants — supported languages and currencies.

These allowlists are the single source of truth for validation.
Adding a new language or currency = add to the set here + provide translation files.
"""

SUPPORTED_LANGUAGES: set[str] = {"en", "pl", "uk", "ru"}

SUPPORTED_CURRENCIES: set[str] = {
    "USD",
    "EUR",
    "GBP",
    "PLN",
    "UAH",
    "CAD",
    "AUD",
    "JPY",
    "CHF",
    "SEK",
    "NOK",
    "DKK",
    "CZK",
    "HUF",
    "BRL",
    "INR",
}
