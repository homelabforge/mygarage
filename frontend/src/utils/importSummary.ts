import type { TFunction } from 'i18next'

/** Per-record-type tallies returned by the JSON import endpoint. */
export type ImportSectionResult = {
  success_count: number
  skipped_count: number
  error_count: number
}

/** The section buckets the JSON import returns, in the order it imports them. */
const SECTIONS = [
  ['service_records', 'vehicles:detail.misc.importServiceRecords'],
  ['fuel_records', 'vehicles:detail.misc.importFuelRecords'],
  ['def_records', 'vehicles:defList.title'],
  ['odometer_records', 'vehicles:detail.misc.importOdometerRecords'],
  ['hours_records', 'vehicles:hoursList.title'],
  ['reminders', 'vehicles:detail.misc.importMaintenanceRecords'],
  ['notes', 'vehicles:noteList.title'],
  ['insurance_policies', 'vehicles:insuranceList.title'],
  ['financing_records', 'vehicles:financingList.title'],
  ['tax_records', 'vehicles:taxList.title'],
  ['toll_tags', 'vehicles:tollTagList.title'],
  ['toll_transactions', 'vehicles:tollList.title'],
  ['warranties', 'vehicles:warrantyList.title'],
  ['spot_rentals', 'vehicles:spotRentalList.title'],
] as const

type SectionKey = (typeof SECTIONS)[number][0]

/** The JSON import response: a bucket per section, then the rows' messages. */
export type ImportJsonResult = Partial<Record<SectionKey, ImportSectionResult>> & {
  errors?: string[]
  warnings?: string[]
}

/** How many of each list the toast shows before it says how many more. */
const LISTED = 5

/** Up to LISTED messages, one a line, then how many more there are. */
function listMessages(messages: readonly string[], t: TFunction): string {
  const shown = messages.slice(0, LISTED).join('\n')
  const rest = messages.length - LISTED
  return rest > 0 ? `${shown}\n${t('vehicles:detail.misc.importMoreCount', { count: rest })}` : shown
}

/**
 * The toast text for a vehicle JSON import: a heading, one line per section
 * the response carries, then the first errors and warnings (N-3, J2).
 */
export function buildImportSummary(result: ImportJsonResult, t: TFunction): string {
  // Qualified keys: this runs outside a component, so there's no bound namespace.
  let message = `${t('vehicles:detail.misc.importSummaryHeading')}\n`
  for (const [key, label] of SECTIONS) {
    const section = result[key]
    if (!section) continue
    message += `\n${t(label)}: ✓ ${t('vehicles:detail.misc.importedCount', { count: section.success_count })}`
    if (section.skipped_count > 0) {
      message += `, ○ ${t('vehicles:detail.misc.skippedCount', { count: section.skipped_count })}`
    }
    if (section.error_count > 0) {
      message += `, ✗ ${t('vehicles:detail.misc.errorCount', { count: section.error_count })}`
    }
  }
  // Backend strings go in verbatim, never through t().
  const lists: Array<[string, string[] | undefined]> = [
    [t('vehicles:detail.misc.importErrorsHeading'), result.errors],
    [t('vehicles:detail.misc.importWarningsHeading'), result.warnings],
  ]
  for (const [heading, messages] of lists) {
    if (messages && messages.length > 0) message += `\n\n${heading}\n${listMessages(messages, t)}`
  }
  return message
}
