/**
 * The instance's `default_country`, read off `/settings/public`.
 *
 * Last rung of the country precedence (`useResolvedCountry`): a vehicle's
 * registration country, then the account's country, then this. Narrowed
 * through `asCountryCode` so a row holding something the app does not know
 * reads as "not set" rather than as a code no profile matches.
 */

import { asCountryCode } from '@/constants/countries'
import type { PublicSetting } from './publicUnitDefaults'

export const DEFAULT_COUNTRY_KEY = 'default_country'

export function readPublicDefaultCountry(
  settings: readonly PublicSetting[] | null | undefined
): string | null {
  const row = (settings ?? []).find((setting) => setting.key === DEFAULT_COUNTRY_KEY)
  return asCountryCode(row?.value)
}
