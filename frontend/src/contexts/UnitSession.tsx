/**
 * Holds a form's units for as long as it's open (#172, R4).
 *
 * A units change can land while a form holds typed text: the Settings card in
 * another tab, a vehicle list refetch, an account refresh. A form that re-read
 * its units would convert the typed number in the new one. So this captures
 * the account set and the enclosing vehicle's odometer unit when it mounts
 * (lazy state, never an effect, so the first frame is already right) and
 * hands those down until the form closes. Reopen it to take new units.
 *
 * Settings editors and read-only drawers aren't wrapped, so they keep
 * repainting the screen behind them.
 */
import { useState, type ComponentType, type ReactElement, type ReactNode } from 'react'
import { useAccountUnitPreference, type UnitPreference } from '../hooks/useUnitPreference'
import { UnitSessionContext } from './unitSessionContext'
import { VehicleUnitScope, useVehicleDistanceUnit, type VehicleDistanceUnit } from './VehicleUnitScope'

interface Captured {
  open: boolean
  account: UnitPreference
  distanceUnit: VehicleDistanceUnit
}

export function UnitSession({
  open = true,
  accountOnly = false,
  children,
}: {
  /** For a drawer that stays mounted while closed: each open takes a fresh capture. */
  open?: boolean
  /** Pin the account set but leave the vehicle scope live. */
  accountOnly?: boolean
  children: ReactNode
}): ReactElement {
  // Inside an outer session these already read the outer pin, so nesting is a no-op.
  const account = useAccountUnitPreference()
  const distanceUnit = useVehicleDistanceUnit()
  const [captured, setCaptured] = useState<Captured>(() => ({ open, account, distanceUnit }))
  // Re-capture on the open edge, during render so no frame shows the old set.
  // Closing keeps the last capture so the exit slide doesn't repaint.
  if (open !== captured.open) {
    setCaptured(open ? { open, account, distanceUnit } : { ...captured, open })
  }

  const pinned = (
    <UnitSessionContext.Provider value={captured.account}>{children}</UnitSessionContext.Provider>
  )
  if (accountOnly) return pinned
  return <VehicleUnitScope distanceUnit={captured.distanceUnit}>{pinned}</VehicleUnitScope>
}

/**
 * Wrap a form so it pins its own units, whoever renders it. The form's hooks
 * run inside the wrapper, which is why this can't just be a tag in its JSX.
 */
export function withUnitSession<P extends object>(Form: ComponentType<P>): (props: P) => ReactElement {
  function Pinned(props: P): ReactElement {
    return (
      <UnitSession>
        <Form {...props} />
      </UnitSession>
    )
  }
  Pinned.displayName = `withUnitSession(${Form.displayName ?? Form.name})`
  return Pinned
}
