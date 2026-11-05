import { useInfiniteQuery, useQuery, useMutation, useQueryClient, type QueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import { invalidateMaintenanceQueries } from '@/hooks/useReminders'
import type { ServiceVisit, ServiceVisitListResponse, ServiceVisitCreate, ServiceVisitUpdate } from '@/types/serviceVisit'

/**
 * A visit write can link, unlink or drop a recall or warranty, and the Recalls
 * and Warranties tabs both show the visit that used them, so they go stale too.
 */
function invalidateVisitWrite(queryClient: QueryClient, vin: string): void {
  invalidateMaintenanceQueries(queryClient, vin)
  void queryClient.invalidateQueries({ queryKey: ['recalls', vin] })
  void queryClient.invalidateQueries({ queryKey: ['warranties', vin] })
}

export function useServiceVisits(vin: string) {
  return useQuery({
    queryKey: ['serviceVisits', vin],
    queryFn: async () => {
      const { data } = await api.get<ServiceVisitListResponse>(
        `/vehicles/${vin}/service-visits`
      )
      return data
    },
    enabled: !!vin,
  })
}

/**
 * One visit by id, for a link from the Recalls or Warranties tab. The list
 * only holds the first page, so an older visit has to come from here.
 */
export function useServiceVisit(vin: string, visitId: number | null) {
  return useQuery({
    queryKey: ['serviceVisits', vin, 'visit', visitId],
    queryFn: async () => {
      const { data } = await api.get<ServiceVisit>(`/vehicles/${vin}/service-visits/${visitId}`)
      return data
    },
    enabled: !!vin && visitId != null,
  })
}

const VISIT_PAGE_SIZE = 100

/**
 * Every visit of the vehicle, newest first, a page at a time: for a picker
 * that must be able to reach a visit older than the first page. Keyed under
 * `['serviceVisits', vin]` so every visit write invalidates it too.
 */
export function useServiceVisitPages(vin: string, options: { enabled?: boolean } = {}) {
  return useInfiniteQuery({
    queryKey: ['serviceVisits', vin, 'pages'],
    queryFn: async ({ pageParam }) => {
      const { data } = await api.get<ServiceVisitListResponse>(`/vehicles/${vin}/service-visits`, {
        params: { skip: pageParam, limit: VISIT_PAGE_SIZE },
      })
      return data
    },
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, page) => n + page.visits.length, 0)
      return loaded < last.total ? loaded : undefined
    },
    enabled: !!vin && (options.enabled ?? true),
  })
}

export function useCreateServiceVisit(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (payload: ServiceVisitCreate) => {
      const { data } = await api.post(`/vehicles/${vin}/service-visits`, payload)
      return data
    },
    // A typed service is the newest event of a rule's type: it can complete
    // a pending reminder and create the next one, so reminders (and the
    // readings the visit synced) are invalidated with the visits.
    onSuccess: () => invalidateVisitWrite(queryClient, vin),
  })
}

export function useUpdateServiceVisit(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, ...payload }: ServiceVisitUpdate & { id: number }) => {
      const { data } = await api.put(`/vehicles/${vin}/service-visits/${id}`, payload)
      return data
    },
    // A typed service is the newest event of a rule's type: it can complete
    // a pending reminder and create the next one, so reminders (and the
    // readings the visit synced) are invalidated with the visits.
    onSuccess: () => invalidateVisitWrite(queryClient, vin),
  })
}

export function useDeleteServiceVisit(vin: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (visitId: number) => {
      await api.delete(`/vehicles/${vin}/service-visits/${visitId}`)
    },
    // A typed service is the newest event of a rule's type: it can complete
    // a pending reminder and create the next one, so reminders (and the
    // readings the visit synced) are invalidated with the visits.
    onSuccess: () => invalidateVisitWrite(queryClient, vin),
  })
}
