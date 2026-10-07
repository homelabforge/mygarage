/**
 * Country codes, the frontend mirror of `backend/app/constants/countries.py`.
 *
 * A person's country (Quick Settings), a vehicle's registration country and
 * the instance's `default_country` setting each hold one ISO 3166-1 alpha-2
 * code. The browser names each code in the reader's language through
 * `Intl.DisplayNames`, so there is nothing to translate here, and the backend
 * validates the same list. Keep the two lists in sync when a code changes.
 */

/** The 249 officially assigned ISO 3166-1 alpha-2 codes. */
export const SUPPORTED_COUNTRY_CODES: readonly string[] = `
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
`
  .trim()
  .split(/\s+/)

const CODES: ReadonlySet<string> = new Set(SUPPORTED_COUNTRY_CODES)

/** The 27 EU member states: a member state with no profile of its own reads the EU baseline. */
export const EU_MEMBER_STATES: readonly string[] = [
  'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE',
  'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
]

/** The code when it is one the backend accepts (after trimming and uppercasing), else null. */
export function asCountryCode(value: string | null | undefined): string | null {
  if (value == null) return null
  const code = value.trim().toUpperCase()
  return CODES.has(code) ? code : null
}

/** A country's name in the reader's language; the code itself on a browser without Intl.DisplayNames. */
export function countryName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'region' }).of(code) ?? code
  } catch {
    return code
  }
}

/** Every supported country as a select option, sorted by its localised name. */
export function countryOptions(locale: string): { value: string; label: string }[] {
  return SUPPORTED_COUNTRY_CODES.map((code) => ({ value: code, label: countryName(code, locale) })).sort(
    (a, b) => a.label.localeCompare(b.label, locale)
  )
}
