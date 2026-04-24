/**
 * Currency symbol resolution helpers.
 *
 * Pure utilities — no React. Use `useCurrencySymbol()` from hooks/ for the
 * React-facing API that pulls from useCurrencyPreference().
 */

const symbolCache = new Map<string, string>()
const GENERIC_CURRENCY_SIGN = '¤' // ¤ — Intl emits this for XXX and weak codes.

/**
 * Return the display symbol for a currency code under a locale.
 *
 * Handles three Intl.NumberFormat failure modes:
 *   - Hard-invalid code (e.g. "BADX") throws RangeError → fall back to the code.
 *   - ISO "no currency" code (e.g. "XXX") silently returns `¤` → fall back to the code.
 *   - Unknown-but-well-formed code → Intl returns the code itself, which is fine.
 */
export function getCurrencySymbol(currencyCode: string, locale: string = 'en-US'): string {
  const key = `${locale}|${currencyCode}`
  const cached = symbolCache.get(key)
  if (cached) return cached

  try {
    const fmt = new Intl.NumberFormat(locale, { style: 'currency', currency: currencyCode })
    const part = fmt.formatToParts(0).find((p) => p.type === 'currency')
    const raw = part?.value ?? currencyCode
    const symbol = raw === GENERIC_CURRENCY_SIGN ? currencyCode : raw
    symbolCache.set(key, symbol)
    return symbol
  } catch {
    symbolCache.set(key, currencyCode)
    return currencyCode
  }
}
