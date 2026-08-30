/**
 * The instance-wide default unit set, as published to clients with no user.
 *
 * Anonymous visitors and every client on an `auth_mode=none` instance skip
 * `/auth/me`, so they have no account to resolve units from (spec D5). The
 * backend has published a full resolved set for them in `/settings/public`
 * since phase 1 (`app/routes/settings.py`, key `default_unit_prefs`); the
 * frontend read `auth_mode` out of that payload and discarded the rest, so an
 * anonymous visitor on a metric-default instance rendered IMPERIAL no matter
 * what the admin had configured.
 *
 * The row's value is a JSON STRING, not a nested object: both writers
 * (`app/migrations/093_add_unit_preferences.py` and
 * `app/services/settings_init.py`) store `json.dumps(unit_set.model_dump(),
 * sort_keys=True)` and the route hands that string back untouched.
 *
 * Parsing degrades WHOLE, mirroring `app/utils/default_unit_prefs.py`: a
 * partial or out-of-vocabulary set yields `null` rather than being patched
 * field by field, because filling the gaps from an imperial default would hand
 * a metric instance imperial pressure. `null` means "this rung has no answer",
 * and the caller drops to the next one. That whole-set validation and the
 * vocabulary it reads now live in `types/units.ts` as `coerceUnitSet` and
 * `UNIT_OPTIONS`: phase 4's browser preference store validates a stored set by
 * exactly the same rule, and the alternative was a second copy of the
 * vocabulary. What is left here is the settings-row half, which is this
 * module's actual subject.
 */

import { coerceUnitSet, type UnitSet } from '@/types/units'
import type { GallonStandard } from '@/utils/units'

/** The settings key the backend publishes the default set under. */
export const DEFAULT_UNIT_PREFS_KEY = 'default_unit_prefs'

/** One row of the `/settings/public` payload. */
export interface PublicSetting {
  key: string
  value?: string | null
}

/**
 * Parse a stored unit set, or return null if it is not a complete, in-vocabulary one.
 *
 * @param raw The settings row's value, as served.
 * @returns The resolved set, or null when there is nothing trustworthy to use.
 */
export function parseUnitSet(raw: string | null | undefined): UnitSet | null {
  if (!raw) return null
  return coerceUnitSet(tryParseJson(raw))
}

/**
 * Find the default unit set in a `/settings/public` payload.
 *
 * @param settings The payload's `settings` array, which may be absent.
 * @returns The resolved set, or null when the instance published none this
 *   client can use.
 */
export function readPublicUnitDefaults(
  settings: readonly PublicSetting[] | null | undefined
): UnitSet | null {
  const row = (settings ?? []).find((setting) => setting.key === DEFAULT_UNIT_PREFS_KEY)
  return parseUnitSet(row?.value)
}

/**
 * The gallon flavour a resolved set implies (D4b).
 *
 * Mirrors `app/utils/unit_formatting.py::_forced_gallon_token`: a `gal_us` or
 * `gal_uk` primary states its own flavour and wins outright even when
 * `secondary_gallon` disagrees. Only a litre primary, which has no flavour of
 * its own, defers to `secondary_gallon`.
 *
 * @param units A resolved unit set.
 * @returns The gallon standard to convert and label with.
 */
export function gallonStandardFor(units: UnitSet): GallonStandard {
  // units-exempt(token-branch): R1's structural exemption in its other spelling. The gallon FLAVOUR is a choice BETWEEN units with no quantity to convert, which is why UNIT_QUANTITIES excludes `secondary_gallon` behind a compile-time completeness proof; this reads `units.volume` because a gallon primary states its own flavour and D4b says it wins. Not deferred work.
  if (units.volume === 'gal_uk') return 'uk'
  // units-exempt(token-branch): the second half of the same rule, and it needs its own pragma because the hatch covers a line and the one above it, so a pair of comparisons on consecutive lines is a pair of sites.
  if (units.volume === 'gal_us') return 'us'
  return units.secondary_gallon
}

/**
 * JSON.parse without the throw.
 *
 * @param raw Candidate JSON text.
 * @returns The parsed value, or null when it is not JSON at all.
 */
function tryParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}
