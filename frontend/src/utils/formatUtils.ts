/**
 * Shared formatting utilities for currency and numbers.
 */

const GENERIC_CURRENCY_SIGN = '¤'

/**
 * Build the Intl-formatted currency string, swapping the generic ¤ sign for
 * the code and falling back to `<CODE> <value>` if Intl throws.
 */
function formatWithIntl(
  num: number,
  currencyCode: string,
  locale: string,
  wholeDollars: boolean
): string {
  const digits = wholeDollars ? 0 : 2
  try {
    const formatted = new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currencyCode,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(num)
    // Intl emits ¤ for ISO "no currency" codes (e.g. XXX). Swap for the code.
    if (formatted.includes(GENERIC_CURRENCY_SIGN)) {
      return formatted.replace(GENERIC_CURRENCY_SIGN, currencyCode)
    }
    return formatted
  } catch {
    return `${currencyCode} ${num.toFixed(digits)}`
  }
}

/**
 * Format a value as currency using Intl.NumberFormat.
 *
 * Handles number, string (parseable), null, and undefined inputs.
 * Returns a formatted currency string or the fallback value.
 *
 * @param value - The value to format
 * @param options - Formatting options
 * @param options.fallback - Value to return when input is null/undefined/zero (default: '-')
 * @param options.wholeDollars - If true, hide cents (default: false)
 * @param options.zeroIsValid - If true, format 0 instead of returning fallback (default: false)
 * @param options.currencyCode - ISO 4217 currency code (default: 'USD')
 * @param options.locale - BCP 47 locale for number formatting (default: 'en-US')
 * @returns Formatted currency string
 */
export function formatCurrency(
  value: number | string | null | undefined,
  options: {
    fallback?: string
    wholeDollars?: boolean
    zeroIsValid?: boolean
    currencyCode?: string
    locale?: string
  } = {}
): string {
  const {
    fallback = '-',
    wholeDollars = false,
    zeroIsValid = false,
    currencyCode = 'USD',
    locale = 'en-US',
  } = options

  if (value === null || value === undefined) return fallback

  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return fallback
  if (num === 0 && !zeroIsValid) return fallback

  return formatWithIntl(num, currencyCode, locale, wholeDollars)
}

/**
 * Format currency with zero fallback for analytics views where zero costs are meaningful.
 */
export function formatCurrencyZero(
  value: number | string | null | undefined,
  options: { currencyCode?: string; locale?: string } = {}
): string {
  const { currencyCode = 'USD', locale = 'en-US' } = options
  const zeroFormatted = formatWithIntl(0, currencyCode, locale, false)
  return formatCurrency(value, { fallback: zeroFormatted, zeroIsValid: true, currencyCode, locale })
}
