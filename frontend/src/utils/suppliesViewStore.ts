/**
 * The supplies page's sort/group/view pick, kept per browser. localStorage on
 * purpose: this is layout taste, not session state, so it should survive a new
 * tab. Every access is guarded because storage throws in a private window or
 * with site data blocked.
 */

import {
  SUPPLY_GROUP_KEYS, SUPPLY_SORT_KEYS, SUPPLY_VIEW_KEYS,
  type SupplyGroupKey, type SupplySortKey, type SupplyViewKey,
} from './supplyListView'

export interface SuppliesViewPrefs {
  sort: SupplySortKey
  group: SupplyGroupKey
  view: SupplyViewKey
}

export const DEFAULT_SUPPLIES_VIEW: SuppliesViewPrefs = { sort: 'name', group: 'none', view: 'grid' }

const KEY = 'mygarage:supplies:view'

const pick = <T extends string>(value: unknown, keys: readonly T[], fallback: T): T =>
  keys.includes(value as T) ? (value as T) : fallback

export function readSuppliesView(): SuppliesViewPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (raw === null) return DEFAULT_SUPPLIES_VIEW
    const parsed = JSON.parse(raw) as Record<string, unknown>
    // Each field stands on its own: one stale token shouldn't drop the rest.
    return {
      sort: pick(parsed.sort, SUPPLY_SORT_KEYS, DEFAULT_SUPPLIES_VIEW.sort),
      group: pick(parsed.group, SUPPLY_GROUP_KEYS, DEFAULT_SUPPLIES_VIEW.group),
      view: pick(parsed.view, SUPPLY_VIEW_KEYS, DEFAULT_SUPPLIES_VIEW.view),
    }
  } catch {
    return DEFAULT_SUPPLIES_VIEW
  }
}

export function rememberSuppliesView(prefs: SuppliesViewPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    // Not remembering the view is a smaller failure than breaking the page.
  }
}
