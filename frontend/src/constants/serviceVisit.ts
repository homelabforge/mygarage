import type { Tone } from '../components/ui'

/**
 * Backend inspection result -> translation key.
 *
 * Domain verified against the `check_inspection_result` CHECK constraint in
 * backend/app/models/service_line_item.py ('passed' | 'failed' |
 * 'needs_attention'). Keys are explicit literals, never built by
 * interpolation. scripts/validate-i18n-usage.ts doesn't follow an indexed map,
 * so __tests__/serviceVisit.test.ts checks each one resolves in English.
 * Unmapped values fall back to INSPECTION_RESULT_FALLBACK_KEY rather than
 * rendering blank.
 *
 * Deliberately reuses the same keys as the InspectionResult picker rather than
 * minting a parallel set: it is the same vocabulary for the same field, and
 * separate keys would let the picker and the badges drift apart per language.
 */
export const INSPECTION_RESULT_KEYS: Record<string, string> = {
  passed: 'inspectionResult.resultPassed',
  failed: 'inspectionResult.resultFailed',
  needs_attention: 'inspectionResult.resultNeedsAttention',
}
export const INSPECTION_RESULT_FALLBACK_KEY = 'inspectionResult.resultUnknown'

// SDQ-B2: off-accent semantic tones, label always shown (colour never sole channel).
const SERVICE_CATEGORY_TONE: Record<string, Tone> = {
  Inspection: 'info',
  Collision: 'danger',
  Detailing: 'success',
  Maintenance: 'default',
  Upgrades: 'muted',
}
export const getServiceCategoryTone = (category?: string): Tone => SERVICE_CATEGORY_TONE[category ?? ''] ?? 'default'

/** The search params that open one service line from another tab. */
export const SERVICE_ITEM_PARAMS = { visit: 'visit', item: 'item' } as const

/** Search string for a link from the Recalls or Warranties tab to the line that used it. */
export const serviceItemSearch = (visitId: number, itemId: number): string =>
  `?tab=service&${SERVICE_ITEM_PARAMS.visit}=${visitId}&${SERVICE_ITEM_PARAMS.item}=${itemId}`
