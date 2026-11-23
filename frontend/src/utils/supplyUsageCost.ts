/**
 * What a supply usage will cost once the visit is saved, the way the server
 * prices it (#301).
 *
 * A saved usage keeps the price it was frozen at. Only a usage with no cost
 * yet takes a price: its own frozen unit cost if it has one, else the supply's
 * current average. Re-pricing everything at today's average made the editor
 * disagree with the History card, which reads what's stored.
 *
 * The server prices as of the visit date (#307), which the editor can't see,
 * so anything it may still move is flagged `estimated`: a price from today's
 * average, a stored estimate, and every saved usage while the date is changed.
 *
 * Money is worked in exact decimals: half a cent rounds up as on the server,
 * where float maths would round 1 × 1.0050 down to 1.00.
 */

type Amount = string | number

export interface SavedUsageCost {
  quantity: Amount
  unit_cost_snapshot?: Amount | null
  cost_snapshot?: Amount | null
  /** Stored at the all-time average; the server settles it once a purchase on or before the visit exists. */
  cost_estimated?: boolean
}

export interface UsageCostEstimate {
  /** In currency units, rounded to cents. */
  cost: number
  /** Nothing to price it with yet: no stored cost, no unit cost, no average. */
  unpriced: boolean
  /**
   * A saved usage with no cost that the save prices after the edit. The server
   * prices a visit's backfills together or not at all: past the money column,
   * it leaves them all unpriced and saves the edit alone.
   */
  backfill: boolean
  /** The save may store a different cost than this one: the server prices as of the visit date. */
  estimated: boolean
}

export interface EstimateOptions {
  /**
   * The visit's date differs from the stored one. The save then re-prices any
   * usage a purchase moved across the old and new dates, frozen ones too.
   */
  dateChanged?: boolean
}

/** Decimal places the server stores: quantity (25, 13), unit cost (15, 4). */
const QUANTITY_PLACES = 13
const UNIT_PLACES = 4

/**
 * A number as the decimal text JSON.stringify sends: the shortest that reads
 * back as it, which the server rounds once. toFixed would round it first, so
 * 1.000000000000045 would go up twice.
 */
function decimalText(value: number): string {
  const text = String(value)
  const exp = /^(-?)(\d+)(?:\.(\d+))?e([+-]\d+)$/.exec(text)
  if (!exp) return text
  const [, sign, whole, frac = '', power] = exp
  const digits = whole + frac
  const point = whole.length + Number(power)
  if (point <= 0) return `${sign}0.${'0'.repeat(-point)}${digits}`
  if (point >= digits.length) return sign + digits + '0'.repeat(point - digits.length)
  return `${sign}${digits.slice(0, point)}.${digits.slice(point)}`
}

/** `value` as an integer count of 10^-places, rounded half up. */
function scaled(value: Amount, places: number): bigint {
  const text = typeof value === 'number' ? decimalText(value) : value.trim()
  const match = /^(-?)(\d*)(?:\.(\d*))?$/.exec(text)
  if (!match) return 0n
  const [, sign, whole, frac = ''] = match
  const padded = (frac + '0'.repeat(places + 1)).slice(0, places + 1)
  let units = BigInt((whole || '0') + padded.slice(0, places))
  if (Number(padded[places]) >= 5) units += 1n
  return sign === '-' ? -units : units
}

/** Whether a quantity the form holds is the saved one, at the server's 13 places. */
export function sameQuantity(quantity: number, saved: Amount): boolean {
  return scaled(quantity, QUANTITY_PLACES) === scaled(saved, QUANTITY_PLACES)
}

/** unit × quantity in cents, half up, as the server's quantize(0.01, ROUND_HALF_UP). */
function priced(unit: Amount, quantity: number): number {
  const product = scaled(unit, UNIT_PLACES) * scaled(quantity, QUANTITY_PLACES)
  const shift = 10n ** BigInt(UNIT_PLACES + QUANTITY_PLACES - 2)
  const cents = (product + shift / 2n) / shift
  return Number(cents) / 100
}

/**
 * The cost a usage will carry after the save.
 *
 * @param quantity Canonical quantity the form will submit.
 * @param saved The usage as stored on this line item, if it was saved before.
 * @param avgUnitCost The supply's current average unit cost, if it has one.
 */
export function estimateUsageCost(
  quantity: number,
  saved: SavedUsageCost | undefined,
  avgUnitCost: Amount | null | undefined,
  { dateChanged = false }: EstimateOptions = {},
): UsageCostEstimate {
  const unchanged = saved != null && sameQuantity(quantity, saved.quantity)
  // An estimate may be settled by the pricer after the edit, so it's labelled.
  // It's no backfill: the pricer's savepoint rolls back only its own writes, so
  // past the money column it keeps the cost the edit leaves it.
  const flagged = saved?.cost_estimated === true
  // Kept as is: the edit never touches a priced usage at the same quantity.
  if (saved?.cost_snapshot != null && unchanged) {
    return { cost: Number(saved.cost_snapshot), unpriced: false, backfill: false, estimated: flagged || dateChanged }
  }
  // Its frozen unit cost prices it, else today's average. A new quantity at a
  // frozen unit is priced by the edit itself; any other saved usage comes out
  // of the edit with no cost, for the backfill after it.
  const unit = saved?.unit_cost_snapshot ?? avgUnitCost
  if (unit == null) return { cost: 0, unpriced: true, backfill: false, estimated: false }
  const backfill = saved != null && (saved.unit_cost_snapshot == null || unchanged)
  // Today's average stands in for the price as of the visit date.
  const fromAverage = saved?.unit_cost_snapshot == null
  return { cost: priced(unit, quantity), unpriced: false, backfill, estimated: fromAverage || flagged || dateChanged }
}
