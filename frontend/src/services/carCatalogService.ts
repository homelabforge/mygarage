/**
 * The make/model picker's catalog (#219 takeover). Bundled, no network calls.
 *
 * Seeded from the catalog Marco Matrella (@marcomatrella) contributed in
 * PR #219, cleaned, plus the backend's motorcycle and truck makes. Make names
 * are the backend's canonical spellings (`backend/app/data/vehicle_makes.json`,
 * held to that by `constants/__tests__/carCatalog.test.ts`).
 */

import catalog from '@/constants/carCatalog.json'
import { withBase } from '@/utils/basePath'

export interface CatalogMake {
  name: string
  slug: string
  /** A file in public/brand-logos/, when the logo dataset has one. */
  logo?: string
  models: string[]
}

const MAKES = catalog as CatalogMake[]

/** Lowercase letters and digits, diacritics removed: Škoda, SKODA and skoda match. */
export function foldKey(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')
}

const BY_KEY = new Map(MAKES.map((make) => [foldKey(make.name), make]))

export function getAllMakes(): CatalogMake[] {
  return MAKES
}

/** The catalog entry for a make however it's written, or undefined. */
export function findMake(name: string | null | undefined): CatalogMake | undefined {
  if (!name) return undefined
  return BY_KEY.get(foldKey(name))
}

export function getModelsForMake(name: string | null | undefined): string[] {
  return findMake(name)?.models ?? []
}

/** Where a logo is served, under a subpath too. */
export function logoUrl(slug: string): string {
  return withBase(`/brand-logos/${slug}.png`)
}

/**
 * The labels matching what's typed, ignoring case and diacritics: the ones
 * that start with it first, then the ones that contain it.
 */
export function filterLabels(labels: string[], query: string, limit = 8): string[] {
  const needle = foldKey(query)
  if (!needle) return []
  const starts: string[] = []
  const contains: string[] = []
  for (const label of labels) {
    const key = foldKey(label)
    if (key.startsWith(needle)) starts.push(label)
    else if (key.includes(needle)) contains.push(label)
  }
  return [...starts, ...contains].slice(0, limit)
}
