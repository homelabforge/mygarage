/**
 * The unit adapter, resolved for the current client.
 *
 * One object per component, closed over whatever `useUnitPreference()` resolved:
 * an authenticated account's `resolved_units`, an explicit anonymous choice, the
 * instance default `/settings/public` publishes, or the post-093 fallback. A
 * call site never sees which rung answered, and never branches on the binary
 * system again:
 *
 *     const u = useUnitFormat()
 *     <Input type="number" step={u.pressure.step} value={form.pressure} ... />
 *     <dd>{u.pressure.format(tire.pressure_kpa)}</dd>
 *
 * A label goes through the caller's own translation, interpolating
 * `u.pressure.label`; this module deliberately holds no keys of its own, since
 * it is not a component and a key here would have to be namespace-qualified for
 * the i18n gate to resolve it.
 *
 * That matters beyond tidiness. `useUnitPreference().system` collapses a custom
 * user's ten choices into one binary answer derived from VOLUME (spec D8), so a
 * user with metric volume and imperial tread reads `'metric'` and every
 * `system === 'imperial'` branch answers "no" for a quantity they chose in
 * inches. The resolved set has the real answer per quantity; this hook is how a
 * component gets at it.
 *
 * `makeUnitFormat` in `utils/unitFormat.ts` is the same thing without React, for
 * an export, a chart transform, or a test.
 */

import { useMemo } from 'react'
import { useUnitPreference } from './useUnitPreference'
import { makeUnitFormat, type UnitFormat } from '../utils/unitFormat'

/**
 * Get the unit formatters for the current client.
 *
 * Memoized on the resolved set and the show-both flag, both of which are stable
 * objects while the preference is unchanged (`presetUnitsFor` returns one object
 * per preset, and `resolved_units` comes from the auth context), so the returned
 * object keeps its identity across renders.
 *
 * @returns One formatter per quantity, closed over the client's resolved units.
 */
export function useUnitFormat(): UnitFormat {
  const { units, showBoth } = useUnitPreference()
  return useMemo(() => makeUnitFormat(units, showBoth), [units, showBoth])
}
