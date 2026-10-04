import { TOLL_COUNTRIES, type TollCountry } from '../constants/tollSystems'

/** The Other choice in both toll dropdowns. A select value only: what's saved is the typed name. */
export const TOLL_OTHER = '__other__'

/** Case, spacing and punctuation don't count, so "touch n go rfid" finds "Touch 'n Go RFID". */
export function tollSystemMatchKey(name: string): string {
  return name.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '')
}

/** Trim and collapse whitespace. The backend does the same before it stores the name. */
export function tidyTollSystem(name: string): string {
  return name.trim().replace(/\s+/g, ' ')
}

/** The listed spelling of a system name, or null when no country lists it. */
export function listedTollSystem(name: string, countries: readonly TollCountry[] = TOLL_COUNTRIES): string | null {
  const key = tollSystemMatchKey(name)
  if (!key) return null
  for (const c of countries) {
    const hit = c.systems.find((s) => tollSystemMatchKey(s) === key)
    if (hit) return hit
  }
  return null
}

/** What a typed name saves as: the listed spelling if it matches one, else the tidied text. */
export function canonicalTollSystem(name: string, countries: readonly TollCountry[] = TOLL_COUNTRIES): string {
  return listedTollSystem(name, countries) ?? tidyTollSystem(name)
}

export function findTollCountry(code: string, countries: readonly TollCountry[] = TOLL_COUNTRIES): TollCountry | undefined {
  return countries.find((c) => c.country === code)
}

/**
 * The country a new tag starts on. Currency counts 2 and language 1, and only
 * a single top scorer counts. Otherwise the user picks.
 */
export function guessTollCountry(
  currencyCode: string,
  language: string,
  countries: readonly TollCountry[] = TOLL_COUNTRIES,
): string | null {
  let best: string | null = null
  let bestScore = 0
  let tied = false
  for (const c of countries) {
    const score = (c.currencies.includes(currencyCode) ? 2 : 0) + (c.languages.includes(language) ? 1 : 0)
    if (score > bestScore) {
      best = c.country
      bestScore = score
      tied = false
    } else if (score > 0 && score === bestScore) {
      tied = true
    }
  }
  return tied ? null : best
}

/** The three toll fields as the form holds them. */
export interface TollSelection {
  /** An ISO code, TOLL_OTHER, or '' for none yet. */
  country: string
  /** A listed system, TOLL_OTHER, or ''. */
  choice: string
  /** The typed name, used when either dropdown is on Other. */
  otherName: string
}

/**
 * Where a form opens. A listed system opens under its country (the guess, if
 * the guess lists it). Anything else, the old literal "Other" included, opens
 * on Other with the saved text, so an untouched save keeps it.
 */
export function initialTollSelection(
  stored: string | null | undefined,
  guess: string | null,
  countries: readonly TollCountry[] = TOLL_COUNTRIES,
): TollSelection {
  if (!stored) return { country: guess ?? '', choice: '', otherName: '' }
  const listed = listedTollSystem(stored, countries)
  if (listed) {
    const homes = countries.filter((c) => c.systems.includes(listed))
    const home = homes.find((c) => c.country === guess) ?? homes[0]
    return { country: home.country, choice: listed, otherName: '' }
  }
  return { country: guess ?? TOLL_OTHER, choice: TOLL_OTHER, otherName: stored }
}

/** True when the name field is showing. */
export function usesOtherName(sel: Pick<TollSelection, 'country' | 'choice'>): boolean {
  return sel.country === TOLL_OTHER || sel.choice === TOLL_OTHER
}

/** The toll_system a selection saves. */
export function selectedTollSystem(sel: TollSelection, countries: readonly TollCountry[] = TOLL_COUNTRIES): string {
  return usesOtherName(sel) ? canonicalTollSystem(sel.otherName, countries) : sel.choice
}

/** The system choice after the country changes: Other and systems the new country lists survive. */
export function choiceForCountry(
  choice: string,
  country: string,
  countries: readonly TollCountry[] = TOLL_COUNTRIES,
): string {
  if (country === '') return ''
  if (country === TOLL_OTHER || choice === TOLL_OTHER) return TOLL_OTHER
  return findTollCountry(country, countries)?.systems.includes(choice) ? choice : ''
}

/** A country's name in the reader's language. Falls back to the code on a browser without Intl.DisplayNames. */
export function tollCountryName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'region' }).of(code) ?? code
  } catch {
    return code
  }
}

export function tollCountryOptions(
  locale: string,
  countries: readonly TollCountry[] = TOLL_COUNTRIES,
): { value: string; label: string }[] {
  return countries
    .map((c) => ({ value: c.country, label: tollCountryName(c.country, locale) }))
    .sort((a, b) => a.label.localeCompare(b.label, locale))
}

export function tollSystemsFor(
  code: string,
  locale: string,
  countries: readonly TollCountry[] = TOLL_COUNTRIES,
): string[] {
  return [...(findTollCountry(code, countries)?.systems ?? [])].sort((a, b) => a.localeCompare(b, locale))
}
