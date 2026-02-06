/**
 * Shared formatting utilities for currency and numbers.
 */

/**
 * Format a value as USD currency.
 *
 * Handles number, string (parseable), null, and undefined inputs.
 * Returns a formatted currency string or the fallback value.
 *
 * @param value - The value to format
 * @param options - Formatting options
 * @param options.fallback - Value to return when input is null/undefined/zero (default: '-')
 * @param options.wholeDollars - If true, hide cents (default: false)
 * @param options.zeroIsValid - If true, format 0 instead of returning fallback (default: false)
 * @returns Formatted currency string
 */
export function formatCurrency(
  value: number | string | null | undefined,
  options: {
    fallback?: string
    wholeDollars?: boolean
    zeroIsValid?: boolean
  } = {}
): string {
  const { fallback = '-', wholeDollars = false, zeroIsValid = false } = options

  if (value === null || value === undefined) return fallback

  const num = typeof value === 'string' ? parseFloat(value) : value
  if (isNaN(num)) return fallback
  if (num === 0 && !zeroIsValid) return fallback

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: wholeDollars ? 0 : 2,
    maximumFractionDigits: wholeDollars ? 0 : 2,
  }).format(num)
}

/**
 * Format currency with $0.00 fallback for analytics views where zero costs are meaningful.
 */
export function formatCurrencyZero(value: number | string | null | undefined): string {
  return formatCurrency(value, { fallback: '$0.00', zeroIsValid: true })
}
