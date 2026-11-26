import { useState } from 'react'

/**
 * The value while `active`, and the last value seen while active once it isn't.
 *
 * For a drawer whose parent nulls its subject in the same render that closes
 * it: the slide-out keeps showing whoever was there instead of flashing empty.
 * Held in state, set during render, so nothing reads a ref while rendering.
 *
 * @param value - What to show right now.
 * @param active - Whether `value` is live. While false, the last live value is returned.
 * @returns `value` while active, otherwise the last value seen while active.
 */
export function useLastWhile<T>(value: T, active: boolean): T {
  const [last, setLast] = useState(value)
  if (active && !Object.is(last, value)) setLast(value)
  return active ? value : last
}
