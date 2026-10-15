import rawCatalog from '../constants/carCatalog.json'

export interface CarMake {
  name: string
  slug: string
  logo: string | null
  models: string[]
}

const catalog: CarMake[] = rawCatalog as CarMake[]

const ALIASES: Record<string, string> = {
  vw: 'volkswagen',
  mercedes: 'mercedes-benz',
  mercedesbenz: 'mercedes-benz',
  alfaromeo: 'alfa-romeo',
  landrover: 'land-rover',
  rollsroyce: 'rolls-royce',
  astonmartin: 'aston-martin',
  greatwall: 'great-wall',
  lynkco: 'lynk-co',
  marutisuzuki: 'maruti-suzuki',
}

function normalizeKey(str: string): string {
  return str.toLowerCase().replace(/[^a-z0-9]/g, '')
}

/**
 * Returns all makes available in the catalog, sorted alphabetically.
 */
export function getAllMakes(): CarMake[] {
  return catalog
}

/**
 * Finds a make in the catalog by exact or fuzzy match (case-insensitive, ignoring punctuation).
 */
export function findMake(query: string | null | undefined): CarMake | undefined {
  if (!query) return undefined
  const norm = normalizeKey(query)
  if (!norm) return undefined

  const aliased = ALIASES[norm] || norm

  return catalog.find(m => {
    const mNorm = normalizeKey(m.name)
    const sNorm = normalizeKey(m.slug)
    return mNorm === aliased || sNorm === aliased || mNorm === norm || sNorm === norm
  })
}

/**
 * Returns the logo image URL for a given logo slug, or null.
 */
export function getLogoUrl(logoSlug: string | null | undefined): string | null {
  if (!logoSlug) return null
  return `https://cdn.jsdelivr.net/gh/filippofilip95/car-logos-dataset@master/logos/thumb/${logoSlug}.png`
}

/**
 * Gets models for a make from the static catalog.
 */
export function getModelsForMake(makeName: string | null | undefined): string[] {
  if (!makeName) return []
  const found = findMake(makeName)
  return found ? found.models : []
}

interface NhtsaModelItem {
  Model_ID: number
  Model_Name: string
  Make_ID: number
  Make_Name: string
}

interface NhtsaResponse {
  Count: number
  Message: string
  Results: NhtsaModelItem[]
}

/**
 * Fallback to NHTSA online API to fetch models for a given make if not found in catalog
 * or to complement catalog models.
 */
export async function fetchNhtsaModels(makeName: string): Promise<string[]> {
  if (!makeName || !makeName.trim()) return []
  try {
    const res = await fetch(
      `https://vpic.nhtsa.dot.gov/api/vehicles/getmodelsformake/${encodeURIComponent(makeName.trim())}?format=json`,
      { signal: AbortSignal.timeout(5000) }
    )
    if (!res.ok) return []
    const data: NhtsaResponse = await res.json()
    if (!data.Results || !Array.isArray(data.Results)) return []
    const set = new Set<string>()
    for (const item of data.Results) {
      if (item.Model_Name && item.Model_Name.trim()) {
        set.add(item.Model_Name.trim())
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  } catch {
    return []
  }
}
