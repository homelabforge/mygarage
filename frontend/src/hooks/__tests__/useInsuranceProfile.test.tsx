import { describe, it, expect, vi } from 'vitest'
import { renderHook } from '@testing-library/react'

// #211: the hook joins the resolved country to its profile's insurance section.
const state: { country: string | null; profile: Record<string, unknown> | null } = {
  country: null,
  profile: null,
}
vi.mock('../useResolvedCountry', () => ({ useResolvedCountry: () => state.country }))
vi.mock('../queries/useCountryProfile', () => ({
  useCountryProfile: (country: string | null) => ({ data: country ? state.profile : null }),
}))

import { useInsuranceProfile } from '../useInsuranceProfile'

describe('useInsuranceProfile', () => {
  it('answers the French profile’s formulas, coverages and bonus-malus scheme', () => {
    state.country = 'FR'
    state.profile = {
      insurance: {
        policy_types: ['Third Party', 'Third Party Extended', 'Full Coverage', 'Other'],
        coverage_keys: ['third_party_liability', 'glass'],
        no_claims: { scheme: 'crm', name: 'Bonus-malus (CRM)', pattern: '^[0-3][.,][0-9]{2}$', example: '0.50' },
      },
    }
    const { result } = renderHook(() => useInsuranceProfile())
    expect(result.current.country).toBe('FR')
    expect(result.current.policyTypes[0]).toBe('Third Party')
    expect(result.current.coverageKeys).toEqual(['third_party_liability', 'glass'])
    expect(result.current.noClaims?.name).toBe('Bonus-malus (CRM)')
  })

  it('answers empty lists and no scheme without a country or without a profile', () => {
    state.country = null
    const { result } = renderHook(() => useInsuranceProfile())
    expect(result.current).toEqual({ country: null, policyTypes: [], coverageKeys: [], noClaims: null })
    state.country = 'US'
    state.profile = null
    expect(renderHook(() => useInsuranceProfile()).result.current.noClaims).toBeNull()
  })

  it('a profile without a no-claims scheme (the EU baseline) names none', () => {
    state.country = 'AT'
    state.profile = { insurance: { policy_types: ['Third Party'], coverage_keys: [], no_claims: null } }
    expect(renderHook(() => useInsuranceProfile()).result.current.noClaims).toBeNull()
  })
})
