/**
 * The browser's own unit preferences, as a subscribable module store.
 *
 * A client with no account is not a client with no preference. Anonymous
 * visitors, and every client on an `auth_mode=none` instance, are exactly the
 * population that cannot use the account path, and until this store existed
 * they could hold `imperial | metric` and nothing else: one bit, where an
 * account holds eleven columns. The Custom controls phase 4 adds would have had
 * nowhere to persist for them.
 *
 * Modelled on the retired `gallonStandardStore.ts`, the store idiom this
 * codebase already uses: a module-level `current`, a `Set` of listeners, and a
 * synchronous read at module load so the very first render already agrees with
 * what is persisted. Four things it does that the gallon store did not.
 *
 * 1. PARSE ONCE AND HOLD. `useSyncExternalStore` calls `getSnapshot` on every
 *    render and throws "The result of getSnapshot should be cached" if it is
 *    handed a fresh object each time, which is precisely what parsing JSON per
 *    read would do. `current` is the parsed object; only a write or a `storage`
 *    event replaces it.
 * 2. VALIDATE WHOLE. One out-of-vocabulary token discards the entire set
 *    (`coerceUnitSet`), mirroring `parse_default_unit_prefs` on the backend.
 *    Half a set puts the client on a silently different unit from the server.
 * 3. MIGRATE THE THREE LEGACY KEYS ONCE, guarded on THIS key being absent and
 *    never on a legacy key being present. Until phase 4 task 5,
 *    `useGallonStandardSync` rewrote `imperial_gallon_standard` from the server
 *    on every boot for every client, so a presence-guarded migration re-ran
 *    forever and overwrote whatever the user chose after it first ran. That
 *    writer is gone, so the three keys are now frozen at whatever they last
 *    said; the absence guard is the correct rule either way and does not move.
 *
 *    ★ AND FREEZING IS THE HALF THAT MATTERS, not absence. "Nothing writes
 *    them any more" was first read here as "they can only be missing", which
 *    reasons about an ABSENT key and skips the PRESENT one that can no longer
 *    heal. A browser holding `imperial_gallon_standard='us'` against a UK
 *    instance is stale forever now that no boot rewrites it, and a migrated
 *    record built from it would be twenty percent wrong in every volume and
 *    every MPG for the life of that browser. This store deliberately does NOT
 *    resolve that here: it has no access to what the instance publishes. It
 *    flags the record instead (`units_are_migrated`), and `useUnitPreference`
 *    rung 2 takes the gallon flavour from the live instance default for a
 *    record carrying that flag. See `migrateLegacy` below.
 * 4. LISTEN FOR `storage`, in the keyless-tolerant form `onStorage` explains.
 *
 * ★ WHY MIGRATION LOOKS AT `unit_preference` AND NOT AT THE OTHER TWO.
 * `unit_preference` is the only one of the three legacy keys that records a
 * user's actual choice of units; the other two are modifiers on it.
 * `imperial_gallon_standard` in particular was never a browser CHOICE at all:
 * it was a CACHE of an instance-wide server value, written for EVERY client on
 * every boot, chosen or not, by a sync hook task 5 deleted. So materialising a
 * full set because that key exists would invent an explicit browser preference
 * that outranks the instance default (`useUnitPreference` rung 2 over rung 3)
 * and pin every such browser to whatever the cache happened to hold. Every
 * browser that carries the key today acquired it that way, so the rule survives
 * its writer, and the same reasoning is why a MIGRATED record does not get to
 * keep the flavour it read out of that cache either.
 *
 * ★ BUT A MODIFIER IS STILL A CHOICE. `show_both_units` is separately settable
 * today by a client with no account, and a browser that set only that has made
 * a real choice. So `StoredUnitPrefs` carries a NULLABLE `units`: a record with
 * `units: null` holds the modifiers and does not activate the units rung. The
 * alternative considered was keeping `show_both_units` on its own key, read
 * independently; one key won because both halves are then written atomically,
 * arrive together across tabs, and give phase 4's card a single thing to write.
 *
 * ★ THE LEGACY KEYS ARE NOT DELETED after migrating. Nothing writes any of them
 * since task 5 retired `useGallonStandardSync`, so there is no write left to
 * race; what remains is that a delete buys nothing this store's own absence
 * guard does not already give it, and it would destroy the only record of a
 * pre-upgrade browser's choice if this store's key were ever cleared.
 */

import {
  coerceUnitSet,
  presetTagFor,
  presetUnitsFor,
  type UnitPreference,
  type UnitSet,
} from '../types/units'
import type { GallonStandard, UnitSystem } from './units'

/** The key this store owns. */
const STORAGE_KEY = 'unit_prefs'

/** The pre-phase-4 keys, each retired by a later task in this phase. */
const LEGACY_SYSTEM_KEY = 'unit_preference'
const LEGACY_GALLON_KEY = 'imperial_gallon_standard'
const LEGACY_SHOW_BOTH_KEY = 'show_both_units'

/**
 * A units choice, as a caller hands one in.
 *
 * `units === null` means the browser holds modifiers only and has no units
 * choice, so `useUnitPreference` falls through to the instance default.
 * `unit_preference` is null in exactly that case and is otherwise DERIVED from
 * `units` by `presetTagFor`: it is on the type so a caller can read the tag back, not
 * so a caller can set it, and `setUnitPrefs` recomputes it. That is deliberate.
 * A stored tag and a stored set can disagree, and a card highlighting
 * "Imperial" over a set the client renders as UK gallons is the exact
 * dishonesty migration 093 fixed on the server side.
 */
export interface UnitPrefsChoice {
  units: UnitSet | null
  unit_preference: UnitPreference | null
  show_both_units: boolean
}

/**
 * What one browser holds, which is a choice plus how the store came by it.
 *
 * ★ THE STORE HOLDS THREE STATES, NOT TWO: no units at all, units held FOR THIS
 * SESSION because `migrateLegacy` derived them, and units CHOSEN and written
 * down. Only the third may be persisted. Collapsing the middle one into the
 * third is how a modifier-only write freezes the module-load gallon guess that
 * `migrateLegacy` exists to avoid persisting (`setShowBothUnits`).
 *
 * ★ AND THE THIRD STATE IS ON THE RECORD RATHER THAN IN A MODULE `let`, because
 * a reader outside this module needs it. `useUnitPreference` rung 2 has to know
 * whether the set it was handed carries a real choice of gallon flavour or the
 * dead `imperial_gallon_standard` cache's last word, and `useSyncExternalStore`
 * gives it exactly one value: this record. A second exported getter would be
 * read during render without a subscription, which is the shape this store
 * exists to replace.
 */
export interface StoredUnitPrefs extends UnitPrefsChoice {
  units_are_migrated: boolean
}

let current: StoredUnitPrefs | null = readPersisted()

const listeners = new Set<() => void>()

/**
 * Subscribe to preference changes, for `useSyncExternalStore`.
 *
 * @param listener Called after any write or cross-tab change.
 * @returns The unsubscribe function.
 */
export function subscribeToUnitPrefs(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/**
 * The current preferences.
 *
 * @returns The held record, or null when this browser holds nothing at all.
 *   The SAME object between changes, because `useSyncExternalStore` requires it.
 */
export function getUnitPrefs(): StoredUnitPrefs | null {
  return current
}

/** Server snapshot: no localStorage during SSR or prerender, so no preference. */
export function getUnitPrefsServerSnapshot(): StoredUnitPrefs | null {
  return null
}

/**
 * Replace the browser's preferences, persist them, and notify subscribers.
 *
 * @param prefs The set and modifiers to hold. Its `unit_preference` is ignored
 *   and recomputed from `units`, so the tag can never contradict the set.
 */
export function setUnitPrefs(prefs: UnitPrefsChoice): void {
  // An explicit units choice, so the set is the browser's own from here on and
  // the legacy keys stop being authoritative for it. With no set there is
  // nothing migrated to flag either, and rung 2 skips a null-units record.
  current = makePrefs(prefs.units, prefs.show_both_units, false)
  persist(current)
  for (const listener of listeners) listener()
}

/**
 * Set the show-both modifier alone, without promoting unchosen units to a choice.
 *
 * ★ Why this is not `setUnitPrefs({ ...current, show_both_units })`. For a
 * browser whose units came from `migrateLegacy`, that set is the one
 * `migrateLegacy` deliberately refused to write down: it was built from the
 * module-load gallon guess, before `/settings/public` resolved. Persisting it
 * as a side effect of a DISPLAY DENSITY toggle freezes that guess forever,
 * which is the same twenty percent error, reached through a different door.
 *
 * So a migration-derived set is persisted as `units: null` and re-derived on
 * the next boot, when the gallon key may finally be right, while the modifier
 * the user actually set is written down.
 *
 * @param showBoth Whether to render both systems.
 */
export function setShowBothUnits(showBoth: boolean): void {
  const migrated = current?.units_are_migrated ?? false
  current = makePrefs(current?.units ?? null, showBoth, migrated)
  persist(makePrefs(migrated ? null : (current.units ?? null), showBoth, false))
  for (const listener of listeners) listener()
}

/**
 * Build a record with the tag derived rather than trusted.
 *
 * @param units The resolved set, or null for a modifiers-only record.
 * @param showBoth Whether to render both systems.
 * @param migrated Whether `units` came from `migrateLegacy` rather than from a
 *   choice this browser made. Always false for a record read back off this
 *   store's own key: persisting a set is what makes it a choice.
 * @returns The record to hold.
 */
function makePrefs(
  units: UnitSet | null,
  showBoth: boolean,
  migrated: boolean
): StoredUnitPrefs {
  return {
    units,
    unit_preference: units === null ? null : presetTagFor(units),
    show_both_units: showBoth,
    units_are_migrated: units !== null && migrated,
  }
}

/**
 * Read what this browser holds, migrating off the legacy keys if it has not yet.
 *
 * @returns The held record, or null when the browser holds nothing usable.
 */
function readPersisted(): StoredUnitPrefs | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    // ★ The guard is the ABSENCE of this key, and nothing else. See the header.
    if (raw === null) return sessionRecord(migrateLegacy(), null)

    const stored = coerceStored(tryParseJson(raw))
    if (stored === null) return null
    if (stored.units !== null) return stored

    // A persisted record holding modifiers but no units. Two browsers reach
    // this: one that genuinely never chose units, and one whose modifier write
    // deliberately withheld a migration-derived set (`setShowBothUnits`).
    // Re-deriving costs the first nothing, because `migrateLegacy` returns null
    // when there is no legacy choice to find, and gives the second back a set
    // that follows the server instead of a frozen guess.
    return sessionRecord(migrateLegacy(), stored.show_both_units)
  } catch {
    // Private mode, or storage disabled entirely.
    return null
  }
}

/**
 * Hold a migration-derived record for this session, flagging it as unchosen.
 *
 * @param migrated What `migrateLegacy` found, or null.
 * @param showBoth The persisted modifier to keep, or null to take the migrated one.
 * @returns The record to hold, or null when there is nothing to hold.
 */
function sessionRecord(
  migrated: StoredUnitPrefs | null,
  showBoth: boolean | null
): StoredUnitPrefs | null {
  if (showBoth === null) return migrated
  return makePrefs(migrated?.units ?? null, showBoth, migrated?.units_are_migrated ?? false)
}

/**
 * Read an untrusted stored record.
 *
 * Unknown keys are tolerated where a unit token is not: a newer tab adding a
 * modifier must not blank this tab's units, while an unreadable token means the
 * two disagree about what the set MEANS and the set is discarded whole.
 *
 * @param value A parsed candidate.
 * @returns The record, or null when it is not one this build can read.
 */
function coerceStored(value: unknown): StoredUnitPrefs | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null

  const candidate = value as Record<string, unknown>
  if (typeof candidate.show_both_units !== 'boolean') return null

  const rawUnits = candidate.units
  if (rawUnits === null || rawUnits === undefined) {
    return makePrefs(null, candidate.show_both_units, false)
  }

  const units = coerceUnitSet(rawUnits)
  if (units === null) return null
  // Only `setUnitPrefs` ever writes a set to this key, so a set read back is a
  // choice this browser made and never a migration's guess.
  return makePrefs(units, candidate.show_both_units, false)
}

/**
 * Fold the three legacy keys into one record for this session.
 *
 * ★ DELIBERATELY DOES NOT PERSIST, and that is the whole point of this
 * function's shape. It reads `imperial_gallon_standard` at MODULE LOAD and an
 * absent key falls back to `us`. Until phase 4 task 5 that read raced
 * `useGallonStandardSync`'s `/settings/public` fetch; since task 5 nothing
 * writes the key at all, so whatever it holds is frozen. Persisting the derived
 * set would freeze it a second time and harder: every later path is guarded on
 * `unit_prefs` being ABSENT, so nothing could ever heal the record.
 *
 * ★ AND NOT PERSISTING IS ONLY HALF THE FIX, which is the correction this
 * comment carries. Two paths reach a gallon flavour that disagrees with the
 * instance: a UK instance whose first post-upgrade settings fetch failed (the
 * key is never written on US instances, so its absence is indistinguishable
 * from normal), and any instance whose admin switches the published flavour,
 * which the instance-default card makes a one-click operation. Re-deriving each
 * boot healed neither once the sync hook was deleted, because there is no
 * writer left to move the key: the SET stopped being frozen and its INPUT
 * stayed frozen. So the record is flagged `units_are_migrated` and
 * `useUnitPreference` rung 2 composes the flavour from the live instance
 * default instead, keeping only the binary system this browser actually chose.
 * The key is still read here, and it is still the answer when the instance
 * publishes nothing at all: that client has no better source, and it is the
 * same value it rendered with before the upgrade.
 *
 * A set the client CHOSE through `setUnitPrefs` is not flagged and is not
 * recomposed. That one is a real choice of flavour and it outranks the
 * instance, which is rung 2's whole reason to sit above rung 3.
 *
 * @returns The migrated record for this session, or null when the browser held
 *   no choice of any kind to migrate.
 */
function migrateLegacy(): StoredUnitPrefs | null {
  const system = readLegacySystem()
  const showBoth = localStorage.getItem(LEGACY_SHOW_BOTH_KEY) === 'true'
  if (system === null && !showBoth) return null

  const gallonStandard: GallonStandard =
    localStorage.getItem(LEGACY_GALLON_KEY) === 'uk' ? 'uk' : 'us'
  const units = system === null ? null : presetUnitsFor(system, gallonStandard)

  return makePrefs(units, showBoth, true)
}

/**
 * Read the legacy browser choice, if it holds one the app recognises.
 *
 * `localStorage.getItem('unit_preference') as UnitSystem` used to hand any
 * stored text straight back as a `UnitSystem`, a value the type says cannot
 * exist. A key the app cannot read is noise rather than a recorded choice.
 *
 * The `units-exempt` marker below is deliberate and is not deferred work: there
 * is no quantity here and nothing to convert, so `validate-units.ts` flags it
 * only because it is fail-closed on an operand whose provenance it cannot see.
 * It moved here with the read it excuses when `useUnitPreference` stopped doing
 * its own parsing; the count of exempt sites is unchanged.
 *
 * @returns The stored system, or null when the browser holds no usable choice.
 */
function readLegacySystem(): UnitSystem | null {
  const stored = localStorage.getItem(LEGACY_SYSTEM_KEY)
  // units-exempt(compare): validating parse of a stored string, not a display conversion.
  return stored === 'imperial' || stored === 'metric' ? stored : null
}

/**
 * Write the record out, tolerating a browser that refuses to store it.
 *
 * The derived tag is not persisted: it is a function of `units`, and a stored
 * copy is one more thing that can go stale against the set beside it.
 *
 * @param prefs The record to persist.
 */
function persist(prefs: StoredUnitPrefs): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ units: prefs.units, show_both_units: prefs.show_both_units })
    )
  } catch {
    // The value still applies for this session even if it cannot be persisted.
  }
}

/**
 * JSON.parse without the throw.
 *
 * @param raw Candidate JSON text.
 * @returns The parsed value, or null when it is not JSON at all.
 */
function tryParseJson(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

/**
 * Re-read on a `storage` event, from another tab or from this one.
 *
 * ★ THE KEY TEST IS DELIBERATELY LENIENT. `SettingsSystemTab` fires
 * `window.dispatchEvent(new Event('storage'))` from its time-format handler
 * (`useTimeFormat` is the listener): a synthetic `Event`, not a
 * `StorageEvent`, with no `key` property at all. Phase 4 task 4 removed the two
 * unit handlers that fired it, so one such site is left rather than three. A
 * handler written `if (event.key !== STORAGE_KEY) return` discards every one of
 * them. The same lenience matches a real `StorageEvent` carrying `key === null`,
 * which is how a whole-store clear arrives.
 *
 * @param event The storage event, real or synthetic.
 */
function onStorage(event: StorageEvent): void {
  if (event.key && event.key !== STORAGE_KEY) return
  current = readPersisted()
  for (const listener of listeners) listener()
}

// `window` is absent under SSR and in a plain node test environment; the store
// still answers from its server snapshot there.
if (typeof window !== 'undefined') {
  window.addEventListener('storage', onStorage)
}
