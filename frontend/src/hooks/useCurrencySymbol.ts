/**
 * Returns the display symbol for the user's preferred currency (e.g. "$", "€", "zł").
 *
 * Memoised on currencyCode + locale. Use inside any component that needs to render
 * a currency prefix without going through formatCurrency().
 */
import { useMemo } from 'react'
import { useCurrencyPreference } from './useCurrencyPreference'
import { getCurrencySymbol } from '../utils/currency'

export function useCurrencySymbol(): string {
  const { currencyCode, locale } = useCurrencyPreference()
  return useMemo(() => getCurrencySymbol(currencyCode, locale), [currencyCode, locale])
}
