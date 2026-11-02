import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'

/**
 * Whether a photo or scan of a document may be read by the configured vision
 * model (#211). The import cards show only when it is on; without it the
 * same fields are typed by hand, and a PDF with a text layer is still read
 * without any model.
 *
 * Read from the public whitelist, like the receipt-parse flag: `/settings`
 * is admin-only, and the person importing a carte grise usually is not one.
 */
export const AI_DOCUMENT_READING_KEY = 'llm_document_reading_enabled'

type PublicSettings = { settings: { key: string; value: string | null }[] }

async function fetchEnabled(): Promise<boolean> {
  const { data } = await api.get<PublicSettings>('/settings/public')
  const row = data?.settings?.find((s) => s.key === AI_DOCUMENT_READING_KEY)
  return (row?.value || 'false').toLowerCase() === 'true'
}

export function useAiDocumentReading(): { enabled: boolean; isLoading: boolean } {
  const query = useQuery({
    queryKey: ['settings', 'public', AI_DOCUMENT_READING_KEY],
    queryFn: fetchEnabled,
    // An admin flips it in Settings; the next import form picks it up.
    staleTime: 60_000,
    retry: false,
  })
  return { enabled: query.data === true, isLoading: query.isLoading }
}
