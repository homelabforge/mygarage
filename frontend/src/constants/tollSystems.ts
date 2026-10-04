/**
 * Toll systems by country, behind the toll tag form's two dropdowns: pick a
 * country, then one of its systems. Adding your country is one row here, and
 * TRANSLATING.md walks through it.
 *
 * - country: the ISO 3166-1 two-letter code. The browser shows the country's
 *   name in each user's language, so there's nothing to translate.
 * - systems: names exactly as the brand writes them. They're saved as-is and
 *   shown as-is in every language, so they never go in a locale file. A system
 *   sold in several countries goes under each one, spelled the same.
 * - currencies, languages: only used to guess the country on a new tag. Codes
 *   from SUPPORTED_CURRENCIES and SUPPORTED_LANGUAGES in constants/i18n.ts.
 *   Leave out a language spoken in lots of countries (en).
 *
 * Order doesn't matter, the form sorts by name. Renaming a system doesn't
 * touch tags already saved with the old spelling.
 */
export interface TollCountry {
  country: string
  currencies: readonly string[]
  languages: readonly string[]
  systems: readonly string[]
}

export const TOLL_COUNTRIES: readonly TollCountry[] = [
  {
    country: 'IT',
    currencies: ['EUR'],
    languages: ['it'],
    systems: ['MooneyGo', 'Telepass', 'UnipolMove'],
  },
  {
    country: 'MY',
    currencies: ['MYR'],
    languages: ['ms'],
    systems: ['SmartTAG', 'Touch \'n Go Card', 'Touch \'n Go RFID'],
  },
  {
    country: 'US',
    currencies: ['USD'],
    languages: [],
    systems: ['E-ZPass', 'EZ TAG', 'FasTrak', 'I-PASS', 'NTTA TollTag', 'SunPass', 'TxTag'],
  },
]
