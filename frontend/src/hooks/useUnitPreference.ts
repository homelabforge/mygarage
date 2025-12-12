/**
 * Hook to access user's unit preference settings.
 *
 * Returns the current user's preferred unit system (imperial/metric) and
 * whether to show both units in displays.
 *
 * Falls back to localStorage for unauthenticated users, or 'imperial' as final fallback.
 */

import { useAuth } from '../contexts/AuthContext';
import type { UnitSystem } from '../utils/units';

interface UnitPreference {
  system: UnitSystem;
  showBoth: boolean;
}

/**
 * Get user's unit preference from AuthContext or localStorage.
 *
 * @returns Object containing system ('imperial' | 'metric') and showBoth (boolean)
 *
 * @example
 * const { system, showBoth } = useUnitPreference();
 * const displayValue = UnitFormatter.formatVolume(gallons, system, showBoth);
 */
export function useUnitPreference(): UnitPreference {
  const { user, isAuthenticated } = useAuth();

  // If authenticated, use user's stored preference
  if (isAuthenticated && user) {
    return {
      system: (user?.unit_preference as UnitSystem) || 'imperial',
      showBoth: user?.show_both_units || false,
    };
  }

  // If not authenticated, use localStorage
  const storedSystem = localStorage.getItem('unit_preference') as UnitSystem | null;
  const storedShowBoth = localStorage.getItem('show_both_units') === 'true';

  return {
    system: storedSystem || 'imperial',
    showBoth: storedShowBoth,
  };
}
