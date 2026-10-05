import { useSyncExternalStore } from 'react'

/** How many drawers are open, nested ones included. Drawer bumps it; anything
 *  that has to get out of a drawer's way (AppToaster) subscribes. */
let count = 0
const listeners = new Set<() => void>()

function emit(): void {
  listeners.forEach((listener) => listener())
}

/** Returns the new count, so Drawer can act on the first open / last close. */
export function markDrawerOpen(): number {
  count += 1
  emit()
  return count
}

export function markDrawerClosed(): number {
  count = Math.max(0, count - 1)
  emit()
  return count
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function anyOpen(): boolean {
  return count > 0
}

export function useAnyDrawerOpen(): boolean {
  return useSyncExternalStore(subscribe, anyOpen)
}
