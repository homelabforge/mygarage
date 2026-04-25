/**
 * Returns the user's preferred currency code and a locale-aware formatCurrency function.
 *
 * Sources (in priority order):
 * 1. Authenticated user's currency_code from DB
 * 2. localStorage 'currency_code'
 * 3. Default: 'USD'
 */
import { useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { languageToLocale } from '../constants/i18n'
import { formatCurrency as formatCurrencyShared } from '../utils/formatUtils'

interface CurrencyPreference {
  currencyCode: string
  locale: string
  formatCurrency: (
    value: number | string | null | undefined,
    options?: { fallback?: string; wholeDollars?: boolean; zeroIsValid?: boolean }
  ) => string
}

export function useCurrencyPreference(): CurrencyPreference {
  const { user } = useAuth()
  const { i18n } = useTranslation()

  const currencyCode = user?.currency_code ?? localStorage.getItem('currency_code') ?? 'USD'
  const locale = languageToLocale(i18n.language)

  const formatCurrency = useCallback(
    (
      value: number | string | null | undefined,
      options: { fallback?: string; wholeDollars?: boolean; zeroIsValid?: boolean } = {}
    ): string => formatCurrencyShared(value, { ...options, currencyCode, locale }),
    [currencyCode, locale]
  )

  return { currencyCode, locale, formatCurrency }
}
