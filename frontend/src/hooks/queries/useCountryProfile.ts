import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import api from '@/services/api'
import type { CountryProfile, CountryProfileSummary } from '@/types/countryProfile'

/**
 * Country profiles are shipped data: they change with a release, not with a
 * click, so they are fetched once per session and kept.
 */
const PROFILE_STALE_TIME = Infinity

export function useCountryProfiles() {
  return useQuery({
    queryKey: ['country-profiles'],
    queryFn: async () => {
      const { data } = await api.get<CountryProfileSummary[]>('/country-profiles')
      return data
    },
    staleTime: PROFILE_STALE_TIME,
  })
}

/**
 * The profile a country code resolves to, or null when the backend has none
 * for it (a 404 is an answer here, not an error: it means "no national rule").
 */
export function useCountryProfile(country: string | null | undefined) {
  return useQuery({
    queryKey: ['country-profiles', country ?? null],
    queryFn: async (): Promise<CountryProfile | null> => {
      try {
        const { data } = await api.get<CountryProfile>(`/country-profiles/${country}`)
        return data
      } catch (error) {
        if (isAxiosError(error) && error.response?.status === 404) return null
        throw error
      }
    },
    enabled: !!country,
    staleTime: PROFILE_STALE_TIME,
  })
}
