/**
 * What the resolved country says about insurance (#211): the formulas to
 * offer first, the coverages to show first, and the name of the no-claims
 * scheme (bonus-malus CRM, SF-Klasse, classe di merito…) with an example.
 *
 * A policy covers several vehicles, so the country is the person's (or the
 * instance's), never one vehicle's registration country.
 */

import { useMemo } from 'react'
import { useCountryProfile } from './queries/useCountryProfile'
import { useResolvedCountry } from './useResolvedCountry'

export interface NoClaimsScheme {
  scheme: string
  name: string
  pattern: string
  example: string
}

export interface InsuranceProfile {
  country: string | null
  /** The profile's formulas, in its order; empty without a profile. */
  policyTypes: string[]
  /** The profile's coverages, in its order; empty without a profile. */
  coverageKeys: string[]
  /** The no-claims scheme, or null where the profile names none. */
  noClaims: NoClaimsScheme | null
}

export function useInsuranceProfile(): InsuranceProfile {
  const country = useResolvedCountry()
  const { data: profile } = useCountryProfile(country)
  return useMemo(() => {
    const insurance = profile?.insurance
    const noClaims = insurance?.no_claims
    return {
      country,
      policyTypes: insurance?.policy_types ?? [],
      coverageKeys: insurance?.coverage_keys ?? [],
      noClaims: noClaims
        ? {
            scheme: noClaims.scheme,
            name: noClaims.name,
            pattern: noClaims.pattern,
            example: noClaims.example,
          }
        : null,
    }
  }, [country, profile])
}
