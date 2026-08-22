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
      system: (user?.unit_preference as UnitSystem) || 'imperial',
      showBoth: user?.show_both_units || false,
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
