import type { TFunction } from 'i18next'

import type { PresetInfo, PresetReadingInfo } from '@/types/livelinkTopicMap'

/**
 * A preset's words in the reader's language.
 *
 * The backend sends English (`description`, each reading's `name`), and it has
 * no translation layer, so the text is keyed here by preset name and reading
 * suffix. A preset this table doesn't know yet falls back to the server's
 * English rather than a raw key. A sensor's stored `display_name` is the
 * user's own words and never comes through here.
 */

interface PresetText {
  readonly descriptionKey: string
  /** By reading suffix (`LEVEL_PCT`). Field names the i18n usage gate reads. */
  readonly readings: Readonly<Record<string, { readonly labelKey: string }>>
}

const PRESET_TEXT: Readonly<Record<string, PresetText>> = {
  mopeka: {
    descriptionKey: 'settings:integrations.presets.mopeka.description',
    readings: {
      LEVEL_PCT: { labelKey: 'settings:integrations.presets.mopeka.readings.LEVEL_PCT' },
      TEMP_C: { labelKey: 'settings:integrations.presets.mopeka.readings.TEMP_C' },
      SENSOR_BATT_PCT: { labelKey: 'settings:integrations.presets.mopeka.readings.SENSOR_BATT_PCT' },
      QUALITY: { labelKey: 'settings:integrations.presets.mopeka.readings.QUALITY' },
      DEPTH_MM: { labelKey: 'settings:integrations.presets.mopeka.readings.DEPTH_MM' },
      REJECTED: { labelKey: 'settings:integrations.presets.mopeka.readings.REJECTED' },
      AVAILABLE: { labelKey: 'settings:integrations.presets.mopeka.readings.AVAILABLE' },
    },
  },
}

/** The preset's description, or the server's for a preset with no entry. */
export function presetDescription(preset: PresetInfo, t: TFunction): string {
  const key = PRESET_TEXT[preset.name]?.descriptionKey
  return key ? t(key) : preset.description
}

/**
 * A reading's label alone, as a form field. The server's names are lowercase
 * so they read naturally after a sensor's name ("Front tank temperature"), so
 * the fallback capitalises.
 */
export function presetReadingLabel(presetName: string, reading: PresetReadingInfo, t: TFunction): string {
  const key = PRESET_TEXT[presetName]?.readings[reading.suffix]?.labelKey
  return key ? t(key) : reading.name.charAt(0).toUpperCase() + reading.name.slice(1)
}
