/**
 * Hook to access user's unit preference settings.
 *
 * Returns the current user's preferred unit system (imperial/metric) and
 * whether to show both units in displays. Also syncs US/UK gallon standard
 * from localStorage into UnitConverter.
 *
 * Falls back to localStorage for unauthenticated users, or 'imperial' as final fallback.
 */

import { useAuth } from '../contexts/AuthContext';
import { UnitConverter, type GallonStandard, type UnitSystem } from '../utils/units';

interface UnitPreference {
  system: UnitSystem;
  showBoth: boolean;
  gallonStandard: GallonStandard;
}

function readGallonStandard(): GallonStandard {
  const stored = localStorage.getItem('imperial_gallon_standard');
  return stored === 'uk' ? 'uk' : 'us';
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
  const gallonStandard = readGallonStandard();
  UnitConverter.setGallonStandard(gallonStandard);

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
