import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { Vehicle } from '../../types/vehicle'

/** One of the wheel layouts the backend knows (#272). */
export type WheelLayoutId = NonNullable<Vehicle['effective_wheel_layout']>

/** Every layout, in the order the picker lists them. */
export const WHEEL_LAYOUT_IDS = [
  'four',
  'two',
  'trike_2f1r',
  'trike_1f2r',
  'dually',
  'none',
] as const satisfies readonly WheelLayoutId[]

interface WheelLayoutText {
  /** "Four wheels", "Two wheels (front and rear)" and so on. */
  layoutLabel: (id: WheelLayoutId) => string
  /** "Automatic: Four wheels", for the option that follows the vehicle type. */
  autoLabel: (id: WheelLayoutId) => string
}

/**
 * The names of the wheel layouts.
 *
 * Literal t() keys only, same as useBrakeText: the i18n usage check can't see
 * a computed key, so a typo would ship the raw key.
 */
export function useWheelLayoutText(): WheelLayoutText {
  const { t } = useTranslation('vehicles')

  // Stable per language, so a caller can memo on these.
  return useMemo(() => {
    const layoutLabels: Record<WheelLayoutId, string> = {
      four: t('wheelLayout.four'),
      two: t('wheelLayout.two'),
      trike_2f1r: t('wheelLayout.trike_2f1r'),
      trike_1f2r: t('wheelLayout.trike_1f2r'),
      dually: t('wheelLayout.dually'),
      none: t('wheelLayout.none'),
    }
    return {
      layoutLabel: (id) => layoutLabels[id],
      autoLabel: (id) => t('wheelLayout.autoNamed', { layout: layoutLabels[id] }),
    }
  }, [t])
}
