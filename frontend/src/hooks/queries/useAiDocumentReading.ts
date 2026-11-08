import { isSettingOn } from '@/utils/settingSwitch'
import type { PublicSetting } from '@/utils/publicUnitDefaults'
import { usePublicSettingsQuery } from './usePublicSettings'

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

function selectEnabled(rows: PublicSetting[]): boolean {
  return isSettingOn(rows.find((row) => row.key === AI_DOCUMENT_READING_KEY)?.value)
}

export function useAiDocumentReading(): { enabled: boolean; isLoading: boolean } {
  // An admin flips it in Settings; the save refreshes the shared query.
  const query = usePublicSettingsQuery(selectEnabled)
  return { enabled: query.data === true, isLoading: query.isLoading }
}
