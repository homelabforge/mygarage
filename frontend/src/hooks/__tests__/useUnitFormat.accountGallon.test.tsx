/**
 * Which answer does a mounted consumption badge paint, and whose is it?
 *
 * ★ THIS FILE'S SUBJECT HAS OUTLIVED TWO MECHANISMS, so read the history before
 * trusting the name. Round 2 fixed the gallon DISPATCH and left a repaint hole:
 * `useResolvedGallonSync` wrote `UnitConverter`'s mutable statics, every
 * consumption reader took the binary `system` and read those statics, and
 * nothing subscribed to them. So the next conversion was right and the pixels
 * were not: a mounted badge read `25.0 MPG` at the moment the converter's
 * flavour had already become `uk`, beside a volume column that had already
 * moved to imperial gallons.
 *
 * Plan 3b task 6b DISSOLVED that hole rather than guarding it, and task 8 then
 * deleted the sync, the subscription and the hook this file used to be named
 * after: with nothing rendering off the mutable statics, writing them and
 * repainting on them was a closed loop. What is asserted here never depended on
 * either mechanism, which is exactly why it survives them, and the assertions
 * that DID depend on the sync went with it rather than being kept as a test of
 * a path no screen takes.
 *
 * The question is WHOSE gallon the badge paints. Rung 1 of `useUnitPreference`
 * must answer with the account's `resolved_units`, and must keep answering with
 * them when the browser-owned store moves underneath it mid-session. The store
 * DISAGREES with the account in the first test (seeded `us`) and is moved to
 * disagree in the third, so 30.0 MPG is false in both unless `resolved_units`
 * wins: regressing rung 1 to `presetUnitsFor(system, cachedGallonStandard)`
 * reads 25.0. The middle test is the anonymous control, where the browser value
 * is the only answer there is.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import {
  IMPERIAL_UNITS,
  makeUser,
  UK_IMPERIAL_UNITS,
  type User,
} from '../../__tests__/factories'
import type { UnitSet } from '../../types/units'

const auth = vi.hoisted(() => ({
  user: null as User | null,
  defaultUnitPrefs: null as UnitSet | null,
}))

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: auth.user,
    isAuthenticated: auth.user !== null,
    defaultUnitPrefs: auth.defaultUnitPrefs,
  }),
}))

import { useUnitFormat } from '../useUnitFormat'

/** Publish an instance-wide default, the way `/settings/public` does. */
function seedInstance(units: UnitSet): void {
  auth.defaultUnitPrefs = units
}

/** A consumption consumer, shaped like VehicleStatisticsCard.tsx's strip. */
function EconomyBadge(): React.ReactElement {
  const u = useUnitFormat()
  // 9.4160546 L/100km is 30.0 MPG on imperial gallons, 25.0 on US ones.
  return <span data-testid="mpg">{u.consumption.formatPrimary(9.4160546)}</span>
}

beforeEach(() => {
  auth.user = null
  localStorage.clear()
  seedInstance(IMPERIAL_UNITS)
})

describe('a mounted consumption badge paints the account\'s own gallon', () => {
  it('★ a mounted badge shows the ACCOUNT\'s MPG, against a US-default instance', () => {
    seedInstance(IMPERIAL_UNITS)
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS })

    render(<EconomyBadge />)

    // Rung 1's `resolved_units` decides, so the badge is right on its first
    // frame. Before task 6b this line read '25.0 MPG' until a repaint the
    // deleted subscription in `useUnitPreference` had to arrange.
    expect(screen.getByTestId('mpg').textContent).toBe('30.0 MPG')

    // ...and the instance default is untouched by the account reading it, which
    // is the constraint that made a plain store write the wrong mechanism.
    expect(auth.defaultUnitPrefs).toStrictEqual(IMPERIAL_UNITS)
  })

  it('a client with no account is left on the instance value, and still renders it', () => {
    seedInstance(UK_IMPERIAL_UNITS)
    auth.user = null

    render(<EconomyBadge />)

    expect(screen.getByTestId('mpg').textContent).toBe('30.0 MPG')
  })

  it('★ holds the account\'s answer when the instance value moves mid-session', () => {
    // The admin's instance-default card rewrites `default_unit_prefs` and
    // `refreshUser` republishes it to every mounted consumer; the account's
    // answer has to win and the badge has to keep saying so. This is the leg
    // that fails if rung 1 ever expands a preset from the instance fallback
    // instead of reading `resolved_units`.
    seedInstance(UK_IMPERIAL_UNITS)
    auth.user = makeUser({ unit_preference: 'custom', resolved_units: UK_IMPERIAL_UNITS })

    const { rerender } = render(<EconomyBadge />)
    expect(screen.getByTestId('mpg').textContent).toBe('30.0 MPG')

    // `act` so the new context value and the resulting render flush before the
    // assertions; without it this asserts against a frame React has not
    // produced yet.
    act(() => {
      seedInstance(IMPERIAL_UNITS)
      rerender(<EconomyBadge />)
    })

    expect(auth.defaultUnitPrefs).toStrictEqual(IMPERIAL_UNITS)
    expect(screen.getByTestId('mpg').textContent).toBe('30.0 MPG')
  })
})
