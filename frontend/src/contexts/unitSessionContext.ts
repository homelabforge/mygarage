/**
 * The account units an open form pinned when it mounted (R4). Null outside any
 * `UnitSession`. Lives on its own so the hook module and the component that
 * fills it don't import each other.
 */
import { createContext } from 'react'
import type { UnitPreference } from '../hooks/useUnitPreference'

export const UnitSessionContext = createContext<UnitPreference | null>(null)
