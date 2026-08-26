/**
 * Hook to access user's unit preference settings.
 *
 * Returns the current user's preferred unit system (imperial/metric) and
 * whether to show both units in displays. Also syncs US/UK gallon standard
 * from localStorage into UnitConverter.
 *
 * Falls back to localStorage for unauthenticated users, or 'imperial' as final fallback.
 */

import { useSyncExternalStore } from 'react';
import { useAuth } from '../contexts/AuthContext';
import type { components } from '../types/api.generated';
import { binarySystemFor } from '../types/units';
import { type GallonStandard, type UnitSystem } from '../utils/units';
import {
  getGallonStandard,
  getGallonStandardServerSnapshot,
  subscribeToGallonStandard,
} from '../utils/gallonStandardStore';

interface UnitPreference {
  system: UnitSystem;
  showBoth: boolean;
  gallonStandard: GallonStandard;
}

/** The parts of an account that decide the binary system. */
type UnitPreferenceFields = Pick<
  components['schemas']['UserResponse'],
  'unit_preference' | 'resolved_units'
>;

/**
 * Collapse a stored unit preference to the binary system every caller expects.
 *
 * Migration 093 materialises per-quantity users as `unit_preference='custom'`,
 * a value `UnitSystem` does not contain. This is the single chokepoint where it
 * becomes 'imperial' or 'metric': ~70 files branch on `system === 'imperial'`,
 * and 'custom' answers "no" to every one of them, so a UK user would have seen
 * imperial numbers rendered under metric labels.
 *
 * @param user The authenticated account's preference fields.
 * @returns The binary unit system to render with.
 */
function systemFor(user: UnitPreferenceFields): UnitSystem {
  if (user.unit_preference === 'custom') {
    // Falling through to the imperial default would put a UK user on US
    // gallons, the exact bug this change exists to fix. The schema makes
    // `resolved_units` required, but a browser holding a cached bundle against
    // an older backend can still be handed a response without it.
    return user.resolved_units ? binarySystemFor(user.resolved_units.volume) : 'imperial';
  }
  return user.unit_preference ?? 'imperial';
}

/**
 * Get user's unit preference from AuthContext or localStorage.
 *
 * @returns Object containing system ('imperial' | 'metric'), showBoth, gallonStandard
 *
 * @example
 * const { system, showBoth } = useUnitPreference();
 * const displayValue = UnitFormatter.formatVolume(gallons, system, showBoth);
 */
export function useUnitPreference(): UnitPreference {
  const { user, isAuthenticated } = useAuth();
  // Subscribed, not read-and-mutated during render: changing the standard has
  // to re-render everything that displays a volume, and a hook body must not
  // write global state (StrictMode runs it twice).
  const gallonStandard = useSyncExternalStore(
    subscribeToGallonStandard,
    getGallonStandard,
    getGallonStandardServerSnapshot,
  );

  // If authenticated, use user's stored preference
  if (isAuthenticated && user) {
    return {
      system: systemFor(user),
      showBoth: user.show_both_units || false,
      gallonStandard,
    };
  }

  // If not authenticated, use localStorage
  const storedSystem = localStorage.getItem('unit_preference') as UnitSystem | null;
  const storedShowBoth = localStorage.getItem('show_both_units') === 'true';

  return {
    system: storedSystem || 'imperial',
    showBoth: storedShowBoth,
    gallonStandard,
  };
}
