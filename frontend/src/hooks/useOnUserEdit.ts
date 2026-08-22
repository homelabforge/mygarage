import { useEffect, useRef } from 'react'
import type { FieldPath, FieldValues, UseFormSubscribe } from 'react-hook-form'

/**
 * Run `handler` when the USER edits one of `fields`. Never on mount, and
 * never in response to the handler's own `setValue`.
 *
 * Derived-field maths (cost = volume by price) must be driven by real input
 * only, and a `watch()` + `useEffect` pair cannot express that: the effect
 * also runs on mount, so opening a saved record recalculates its stored
 * values and quietly replaces them. A receipt total that included a car wash
 * became volume by price just by being looked at.
 *
 * The "skip the first run" flag the record forms used to carry did not
 * prevent that. It was a piece of `useState` listed in the effect's OWN
 * dependency array, so flipping it re-ran the effect one render later with
 * the guard already down: it moved the overwrite by one render and nothing
 * else.
 *
 * RHF's subscribe callback reports `type: 'change'` for a real input event
 * and `undefined` for a programmatic `setValue`. Keying on that gives both
 * properties at once: no mount-time run, and no feedback loop when the
 * handler itself writes a field (which is how tank size drives volume,
 * which in turn drives cost).
 */
export function useOnUserEdit<T extends FieldValues>(
  subscribe: UseFormSubscribe<T>,
  fields: readonly FieldPath<T>[],
  handler: (values: T, name: FieldPath<T>) => void,
): void {
  // Held in a ref so callers can pass an inline closure over props and state
  // without re-subscribing on every render.
  const handlerRef = useRef(handler)
  useEffect(() => {
    handlerRef.current = handler
  })

  // Joined into a string so an inline array literal is still a stable dep.
  const watched = fields.join(' ')

  useEffect(() => {
    const names = new Set(watched.split(' '))
    return subscribe({
      formState: { values: true },
      callback: ({ values, name, type }) => {
        if (type !== 'change' || !name || !names.has(name)) return
        handlerRef.current(values as T, name as FieldPath<T>)
      },
    })
  }, [subscribe, watched])
}
