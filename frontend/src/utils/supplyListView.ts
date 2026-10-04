import type { Supply } from '@/types/supplies'

export const SUPPLY_SORT_KEYS = ['name', 'stock', 'category'] as const
export type SupplySortKey = (typeof SUPPLY_SORT_KEYS)[number]
export const SUPPLY_GROUP_KEYS = ['none', 'category', 'vehicle'] as const
export type SupplyGroupKey = (typeof SUPPLY_GROUP_KEYS)[number]
export const SUPPLY_VIEW_KEYS = ['grid', 'list'] as const
export type SupplyViewKey = (typeof SUPPLY_VIEW_KEYS)[number]

export interface SupplyFilters {
  query: string
  category: string | null // canonical spelling from canonicalCategories; null = all
  vehicle: 'all' | 'shared' | string // a VIN otherwise
  outOfStock: boolean
}

// on_hand is a decimal string off the wire, so compare the number, not the text.
export function isOutOfStock(supply: Supply): boolean {
  return Number(supply.on_hand) <= 0
}

/**
 * Distinct categories, merged case-insensitively, each under its most common
 * spelling (tie goes to the spelling seen first), sorted for display.
 */
export function canonicalCategories(supplies: Supply[]): string[] {
  const buckets = new Map<string, Map<string, number>>()
  for (const s of supplies) {
    if (!s.category) continue
    const key = s.category.toLowerCase()
    const spellings = buckets.get(key) ?? new Map<string, number>()
    spellings.set(s.category, (spellings.get(s.category) ?? 0) + 1)
    buckets.set(key, spellings)
  }
  const canonical: string[] = []
  for (const spellings of buckets.values()) {
    let best = ''
    let bestCount = 0
    for (const [spelling, count] of spellings) {
      if (count > bestCount) {
        best = spelling
        bestCount = count
      }
    }
    canonical.push(best)
  }
  return canonical.sort((a, b) => a.localeCompare(b))
}

export function sortSupplies(supplies: Supply[], sort: SupplySortKey): Supply[] {
  const copy = [...supplies]
  const byName = (a: Supply, b: Supply): number => a.name.localeCompare(b.name)
  if (sort === 'stock') {
    // Ranks keep counts and litres from ever comparing against each other.
    const rank = (s: Supply): number => {
      if (isOutOfStock(s)) return 0
      return s.unit_type === 'count' ? 1 : 2
    }
    return copy.sort((a, b) => {
      const ra = rank(a)
      const rb = rank(b)
      if (ra !== rb) return ra - rb
      if (ra === 0) return byName(a, b)
      return Number(a.on_hand) - Number(b.on_hand) || byName(a, b)
    })
  }
  if (sort === 'category') {
    return copy.sort((a, b) => {
      if (!a.category && !b.category) return byName(a, b)
      if (!a.category) return 1
      if (!b.category) return -1
      return a.category.toLowerCase().localeCompare(b.category.toLowerCase()) || byName(a, b)
    })
  }
  return copy.sort(byName)
}

export interface SupplyGroup {
  kind: SupplyGroupKey
  /** canonical category or a VIN; null = the trailing bucket (no category / shared) */
  value: string | null
  supplies: Supply[]
}

/**
 * Buckets an already-sorted list without re-sorting inside groups. Category
 * buckets merge case-insensitively under the canonical spelling.
 */
export function groupSupplies(
  sorted: Supply[],
  group: SupplyGroupKey,
  vehicleLabelFor: (vin: string) => string,
): SupplyGroup[] {
  if (group === 'none') {
    return [{ kind: 'none', value: null, supplies: sorted }]
  }
  const spellings = group === 'category' ? canonicalCategories(sorted) : []
  const canonicalFor = new Map(spellings.map((s) => [s.toLowerCase(), s]))
  const buckets = new Map<string | null, Supply[]>()
  for (const s of sorted) {
    const value = group === 'category'
      ? (s.category ? (canonicalFor.get(s.category.toLowerCase()) ?? s.category) : null)
      : (s.vin ?? null)
    const bucket = buckets.get(value) ?? []
    bucket.push(s)
    buckets.set(value, bucket)
  }
  const labelFor = (value: string): string => (group === 'vehicle' ? vehicleLabelFor(value) : value)
  const named = [...buckets.entries()]
    .filter((entry): entry is [string, Supply[]] => entry[0] !== null)
    .sort((a, b) => labelFor(a[0]).localeCompare(labelFor(b[0])))
    .map(([value, supplies]) => ({ kind: group, value, supplies }))
  const trailing = buckets.get(null)
  return trailing ? [...named, { kind: group, value: null, supplies: trailing }] : named
}

export function filterSupplies(supplies: Supply[], filters: SupplyFilters): Supply[] {
  const query = filters.query.trim().toLowerCase()
  const category = filters.category?.toLowerCase() ?? null
  return supplies.filter((s) => {
    if (query) {
      const haystack = [s.name, s.part_number, s.barcode, s.category, s.notes]
        .map((field) => (field ?? '').toLowerCase())
      if (!haystack.some((field) => field.includes(query))) return false
    }
    if (category !== null && (s.category ?? '').toLowerCase() !== category) return false
    if (filters.vehicle === 'shared') {
      if (s.vin != null) return false
    } else if (filters.vehicle !== 'all' && s.vin !== filters.vehicle) {
      return false
    }
    if (filters.outOfStock && !isOutOfStock(s)) return false
    return true
  })
}
