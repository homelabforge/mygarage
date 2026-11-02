/**
 * The name and description a reminder pack shows (#211).
 *
 * A shipped pack is a JSON file with English copy; its id is stable, so the
 * UI looks the id up in the `vehicles:reminderPacks` bundle and falls back
 * to the file's own text for a pack no bundle knows (a new file, a language
 * without the key). A pack a person saved on this instance is theirs: its
 * name is shown as typed, never translated.
 */

import type { TFunction } from 'i18next'

export interface PackLike {
  id: string
  name: string
  description?: string | null
  is_custom?: boolean
}

export function packDisplayName(pack: PackLike, t: TFunction): string {
  if (pack.is_custom) return pack.name
  return t(`vehicles:reminderPacks.${pack.id}.name`, { defaultValue: pack.name })
}

export function packDescription(pack: PackLike, t: TFunction): string {
  const fallback = pack.description ?? ''
  if (pack.is_custom) return fallback
  return t(`vehicles:reminderPacks.${pack.id}.description`, { defaultValue: fallback })
}
