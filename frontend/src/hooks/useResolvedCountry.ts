/**
 * The country whose rules apply, resolved the same way the backend does
 * (`country_profile_service.resolve_country`):
 *
 * 1. the vehicle's `registration_country` (a cross-border household registers
 *    a car abroad);
 * 2. this person's own country (Quick Settings; the account, or this browser
 *    when sign-in is off);
 * 3. the instance's `default_country` setting;
 * 4. null: no national rule applies, today's behaviour.
 */

import { useAuth } from '@/contexts/AuthContext'
import { asCountryCode } from '@/constants/countries'
import { usePersonalPreference } from './usePersonalPreference'

/** Where the person's country lives in this browser when there is no account. */
export const COUNTRY_STORAGE_KEY = 'country'

/** This person's own country, without the vehicle or instance rungs. */
export function useCountryPreference(): string | null {
  return usePersonalPreference(COUNTRY_STORAGE_KEY, COUNTRY_STORAGE_KEY, asCountryCode)
}

export function useResolvedCountry(
  vehicle?: { registration_country?: string | null } | null
): string | null {
  const { defaultCountry } = useAuth()
  const personal = useCountryPreference()
  return asCountryCode(vehicle?.registration_country) ?? personal ?? defaultCountry
}
