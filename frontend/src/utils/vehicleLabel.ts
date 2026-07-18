import type { QuickEntryVehicle } from '@/hooks/queries/useQuickEntryVehicles'

/**
 * Human label for a vehicle: "Nickname (Year Make Model)", or just the
 * year/make/model (falling back to the VIN) when the nickname matches or is absent.
 */
export function vehicleLabel(v: QuickEntryVehicle): string {
  const yearMakeModel = [v.year, v.make, v.model].filter(Boolean).join(' ')
  return v.nickname !== yearMakeModel
    ? `${v.nickname} (${yearMakeModel || v.vin})`
    : yearMakeModel || v.vin
}
