import type { QuickEntryVehicle } from '@/hooks/queries/useQuickEntryVehicles'
import { vinForDisplay } from './vehicleIdentifier'

/** "Year Make Model", skipping whatever is unknown; empty when nothing is. */
export function yearMakeModel(v: {
  year?: number | null
  make?: string | null
  model?: string | null
}): string {
  return [v.year, v.make, v.model].filter(Boolean).join(' ')
}

/**
 * Human label for a vehicle: "Nickname (Year Make Model)", or just the
 * year/make/model (falling back to the VIN) when the nickname matches or is absent.
 * A generated key (a vehicle without a VIN, #226) is never shown.
 */
export function vehicleLabel(v: QuickEntryVehicle): string {
  const ymm = yearMakeModel(v)
  const fallback = ymm || vinForDisplay(v.vin)
  if (v.nickname && v.nickname !== ymm) return fallback ? `${v.nickname} (${fallback})` : v.nickname
  return fallback || v.nickname || ''
}
