import type { TFunction } from 'i18next'

/** Per-record-type tallies returned by the JSON import endpoint. */
export type ImportSectionResult = {
  success_count: number
  skipped_count: number
  error_count: number
}

/**
 * The toast text for a vehicle JSON import: a heading, then one line per
 * section the response carries, in the order the backend imports them.
 */
export function buildImportSummary(
  result: Record<string, ImportSectionResult | undefined>,
  t: TFunction,
): string {
  // Qualified keys: this runs outside a component, so there's no bound namespace.
  const sections: Array<[string, ImportSectionResult | undefined]> = [
    [t('vehicles:detail.misc.importServiceRecords'), result.service_records],
    [t('vehicles:detail.misc.importFuelRecords'), result.fuel_records],
    [t('vehicles:defList.title'), result.def_records],
    [t('vehicles:detail.misc.importOdometerRecords'), result.odometer_records],
    [t('vehicles:hoursList.title'), result.hours_records],
    [t('vehicles:detail.misc.importMaintenanceRecords'), result.reminders],
    [t('vehicles:noteList.title'), result.notes],
    [t('vehicles:insuranceList.title'), result.insurance_policies],
  ]

  let message = `${t('vehicles:detail.misc.importSummaryHeading')}\n`
  for (const [label, section] of sections) {
    if (!section) continue
    message += `\n${label}: ✓ ${t('vehicles:detail.misc.importedCount', { count: section.success_count })}`
    if (section.skipped_count > 0) {
      message += `, ○ ${t('vehicles:detail.misc.skippedCount', { count: section.skipped_count })}`
    }
    if (section.error_count > 0) {
      message += `, ✗ ${t('vehicles:detail.misc.errorCount', { count: section.error_count })}`
    }
  }
  return message
}
