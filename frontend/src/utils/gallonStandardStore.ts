import { UnitConverter, type GallonStandard } from './units'

/**
 * The active imperial gallon standard, as a subscribable module store.
 *
 * `UnitConverter` keeps the standard in a static field because non-React
 * callers (formatters, PDF-adjacent helpers) convert without a hook. That field
 * alone is not enough for React: writing it triggers no re-render, so a
 * component that had already mounted kept showing US gallons after the setting
 * resolved. It was also being written from inside a hook's render body, which
 * is a side effect React may run twice under StrictMode.
 *
 * This store owns the value instead. It initialises SYNCHRONOUSLY from
 * localStorage at module load and pushes that into UnitConverter before anything
 * can read either one, so the very first render and any non-React conversion
 * already agree with the persisted setting. `useSyncExternalStore` then keeps
 * subscribed components in step with later changes.
 */

const STORAGE_KEY = 'imperial_gallon_standard'

function readPersisted(): GallonStandard {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'uk' ? 'uk' : 'us'
  } catch {
    // Private mode, or storage disabled entirely.
    return 'us'
  }
}

let current: GallonStandard = readPersisted()
// Before any snapshot is handed out, so a non-React caller cannot read a
// converter that disagrees with the store.
UnitConverter.setGallonStandard(current)

const listeners = new Set<() => void>()

export function subscribeToGallonStandard(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getGallonStandard(): GallonStandard {
  return current
}

/** Server snapshot: no localStorage during SSR/prerender, so the US default. */
export function getGallonStandardServerSnapshot(): GallonStandard {
  return 'us'
}

/**
 * Set the active standard, persist it, and notify subscribers.
 *
 * Used by the settings save and by the sync-from-server hook. A no-op when the
 * value is unchanged, so a re-sync cannot cause a render loop.
 */
export function setGallonStandard(standard: GallonStandard): void {
  if (standard === current) return
  current = standard
  try {
    localStorage.setItem(STORAGE_KEY, standard)
  } catch {
    // Value still applies for this session even if it cannot be persisted.
  }
  UnitConverter.setGallonStandard(standard)
  for (const listener of listeners) listener()
}
