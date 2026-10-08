import { describe, it, expect } from 'vitest'
import openapi from '../../types/openapi.json'
import {
  COVERAGES,
  COVERAGE_ORDER,
  coverageLayout,
  coverageRows,
  coverageSlots,
  coveragesToApi,
} from '../insuranceCoverages'
import type { Coverage, CoverageKey } from '../../types/insurance'

/** The backend's own catalogue order, as the generated schema records it. */
const backendEntry = (
  openapi as unknown as {
    components: {
      schemas: {
        CoverageEntryResponse: {
          properties: { coverage_key: { enum: string[] } }
          'x-coverage-slots': Record<string, Record<string, string>>
        }
      }
    }
  }
).components.schemas.CoverageEntryResponse
const backendOrder: string[] = backendEntry.properties.coverage_key.enum
const backendSlots = backendEntry['x-coverage-slots']

describe('the standard coverage catalogue', () => {
  it('lists exactly the coverages the backend does, in the same order', () => {
    // `Record<CoverageKey, …>` already fails `tsc` on a missing or stray key.
    // This is the part types cannot see: the ORDER, which is the layout of
    // every policy card and every coverage form.
    expect(COVERAGE_ORDER).toEqual(backendOrder)
  })

  it('gives every coverage a label', () => {
    for (const key of COVERAGE_ORDER) {
      expect(COVERAGES[key].labelKey, key).toMatch(/^forms:insuranceCoverages\./)
    }
  })

  it('never offers a second limit without a first', () => {
    for (const key of COVERAGE_ORDER) {
      const meta = COVERAGES[key]
      expect(meta.secondary && !meta.primary, key).toBeFalsy()
    }
  })

  it('offers each coverage its slots in declarations-page column order', () => {
    const names = (key: CoverageKey) => coverageSlots(key).map(([name]) => name)
    expect(names('bodily_injury')).toEqual(['limit_primary', 'limit_secondary', 'premium'])
    expect(names('comprehensive')).toEqual(['deductible', 'premium'])
    expect(names('roadside_assistance')).toEqual(['premium'])
  })

  it('has exactly the slots, in the order and of the kinds, the backend has', () => {
    // The shape the backend publishes beside the enum. A mismatch here is
    // silent and destructive in one direction: a slot only the backend has
    // renders no input, and saving the form would clear the stored amount.
    const ours = Object.fromEntries(
      COVERAGE_ORDER.map((key) => [
        key,
        Object.fromEntries(coverageSlots(key).map(([name, slot]) => [name, slot.kind])),
      ])
    )
    expect(ours).toEqual(backendSlots)
  })
})

describe('the checklist the form holds', () => {
  it('carries every coverage, ticking only the ones the vehicle has', () => {
    const rows = coverageRows([{ coverage_key: 'collision', deductible: '500.00' }])
    expect(rows).toHaveLength(COVERAGE_ORDER.length)
    const collision = rows.find((row) => row.coverage_key === 'collision')
    expect(collision?.included).toBe(true)
    expect(collision?.deductible).toBe(500)
    expect(rows.find((row) => row.coverage_key === 'glass')?.included).toBe(false)
  })

  it('puts every coverage at the same index for every vehicle', () => {
    const a = coverageRows([{ coverage_key: 'collision' }]).map((row) => row.coverage_key)
    const b = coverageRows([{ coverage_key: 'glass' }]).map((row) => row.coverage_key)
    expect(a).toEqual(b)
  })

  it('ticks a coverage that is carried with no amounts at all', () => {
    const rows = coverageRows([{ coverage_key: 'roadside_assistance' }])
    const roadside = rows.find((row) => row.coverage_key === 'roadside_assistance')
    expect(roadside?.included).toBe(true)
    expect(roadside?.premium).toBeUndefined()
  })

  it('sends only the ticked coverages', () => {
    const rows = coverageRows([{ coverage_key: 'collision', deductible: '500.00' }])
    expect(coveragesToApi(rows)).toEqual([
      {
        coverage_key: 'collision',
        limit_primary: null,
        limit_secondary: null,
        deductible: '500',
        premium: null,
      },
    ])
  })

  it('drops an amount the coverage it was left on has no slot for', () => {
    // Typed under one coverage, then unticked and ticked under another: the
    // API rejects an amount it has nowhere to show, so it never leaves here.
    const rows = coverageRows().map((row) =>
      row.coverage_key === 'collision'
        ? { ...row, included: true, limit_primary: 100, deductible: 500 }
        : row
    )
    const [sent] = coveragesToApi(rows)
    expect(sent.limit_primary).toBeNull()
    expect(sent.deductible).toBe('500')
  })

  it('round-trips what a vehicle carries', () => {
    const carried: Coverage[] = [
      {
        coverage_key: 'bodily_injury',
        limit_primary: '100000',
        limit_secondary: '300000',
        premium: '55',
      },
      { coverage_key: 'roadside_assistance' },
    ]
    const again = coveragesToApi(coverageRows(carried))
    expect(again.map((item) => item.coverage_key)).toEqual([
      'bodily_injury',
      'roadside_assistance',
    ])
    expect(again[0].limit_secondary).toBe('300000')
    expect(again[1].premium).toBeNull()
  })
})

describe('the European catalogue (#211)', () => {
  const backendRegions = (
    openapi as unknown as {
      components: { schemas: { CoverageEntryResponse: { 'x-coverage-regions': Record<string, string[]> } } }
    }
  ).components.schemas.CoverageEntryResponse['x-coverage-regions']

  it('sells each coverage on the markets the backend says', () => {
    const ours = Object.fromEntries(COVERAGE_ORDER.map((key) => [key, COVERAGES[key].regions]))
    expect(ours).toEqual(backendRegions)
  })

  it('lays a French form out with the profile’s coverages first and the rest behind « more »', () => {
    const french = ['third_party_liability', 'driver_protection', 'glass', 'theft']
    const { shown, more } = coverageLayout(french)
    expect(shown).toEqual(french)
    expect(more).toEqual(COVERAGE_ORDER.filter((key) => !french.includes(key)))
    expect(more).toContain('collision')
    expect(more).not.toContain('glass')
  })

  it('shows everything in catalogue order without a profile, and ignores a key it does not know', () => {
    expect(coverageLayout(undefined)).toEqual({ shown: COVERAGE_ORDER, more: [] })
    expect(coverageLayout([])).toEqual({ shown: COVERAGE_ORDER, more: [] })
    expect(coverageLayout(['umbrella'])).toEqual({ shown: COVERAGE_ORDER, more: [] })
    expect(coverageLayout(['umbrella', 'theft']).shown).toEqual(['theft'])
  })
})
