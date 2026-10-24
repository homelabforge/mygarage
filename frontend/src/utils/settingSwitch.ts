/**
 * How the frontend reads an on/off setting's stored text.
 *
 * The backend reads every switch with one vocabulary (R5,
 * `SWITCH_ON_VALUES` / `SWITCH_OFF_VALUES` in
 * `backend/app/services/settings_service.py`): after a strip and lower-casing,
 * `true`, `1`, `yes` and `on` are on; anything else is off; a blank or missing
 * value falls back to the caller's default. Writers now store a switch as
 * `"true"` or `"false"`, but a row written before that may still hold `"1"` or
 * `"yes"`. Comparing the text with `'true'` exactly showed such a switch as
 * off while the backend honoured it as on.
 */

/** The words that read as on, after a strip and lower-casing (R5). */
const SWITCH_ON_VALUES: ReadonlySet<string> = new Set(['true', '1', 'yes', 'on'])

/**
 * Read a stored on/off setting with the backend's vocabulary.
 *
 * @param value The setting's stored text, as served.
 * @param fallback What a blank or missing value reads as.
 * @returns True for an on word in any case; the fallback for blank or nullish;
 *   false for anything else, so an unknown word never turns a feature on.
 */
export function isSettingOn(value: string | null | undefined, fallback = false): boolean {
  if (value == null) return fallback
  const word = value.trim().toLowerCase()
  if (word === '') return fallback
  return SWITCH_ON_VALUES.has(word)
}
