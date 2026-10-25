/**
 * Every component reads units through `useUnitPreference` (or the account
 * hook), so a vehicle scope laid inside that hook reaches all of them (#172).
 * A file that reads the account set some other way would silently bypass the
 * scope: its numbers would render in the account's unit on a vehicle page
 * that labels everything else in the vehicle's. This list is the whole set of
 * files allowed to touch the raw sources; adding one is a design decision.
 *
 * LiveLink readings go through `telemetryUnits.ts`, which takes its
 * formatters from `useUnitFormat`, so they never match here either. Threshold
 * alerts are rendered in the user's units by the backend; the one thing that
 * prints raw is an odometer key the backend didn't normalise.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const SRC = resolve(__dirname, '..')
const RAW_SOURCE = /resolved_units|defaultUnitPrefs|makeUnitFormat\(/

const ALLOWED = new Set([
  'components/settings/InstanceUnitDefaultsCard.tsx',
  'components/settings/UnitPreferencesCard.tsx',
  'contexts/AuthContext.tsx',
  'hooks/useUnitFormat.ts',
  'hooks/useUnitPreference.ts',
  'types/api.generated.ts',
  'utils/supplyUnits.ts',
  'utils/unitFormat.ts',
  'utils/units.ts',
])

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === '__tests__' ? [] : walk(path)
    return /\.(ts|tsx)$/.test(name) && !/\.test\.tsx?$/.test(name) ? [path] : []
  })
}

describe('the unit chokepoint', () => {
  it('no other file reads the account unit set directly', () => {
    const offenders = walk(SRC)
      .map((path) => relative(SRC, path).replaceAll('\\', '/'))
      .filter((rel) => !ALLOWED.has(rel))
      .filter((rel) => RAW_SOURCE.test(readFileSync(join(SRC, rel), 'utf-8')))
    expect(offenders).toEqual([])
  })
})
