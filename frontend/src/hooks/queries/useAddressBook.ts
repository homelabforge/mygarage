import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import type { AddressBookListResponse } from '@/types/addressBook'

/**
 * Address-book entries (the shared contact/vendor list) for supplier/vendor
 * pickers. GET /address-book returns the full unpaginated list.
 */
export function useAddressBookEntries() {
  return useQuery({
    queryKey: ['address-book', 'all'],
    queryFn: async () => {
      const { data } = await api.get<AddressBookListResponse>('/address-book')
      return data.entries
    },
    staleTime: 60_000,
  })
}
