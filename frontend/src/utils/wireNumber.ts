/**
 * API decimals arrive as strings (or numbers, or null), and the formatters and
 * unit utils take `number | null`. A blank string counts as no value, not 0.
 */
export const num = (v: number | string | null | undefined): number | null =>
  v === null || v === undefined || v === '' ? null : Number(v)
