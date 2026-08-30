/**
 * The Units card: the only place a client's unit preferences are written.
 *
 * ★ IT REPAIRS TWO LIVE REGRESSIONS, which is why it is not a pure extraction.
 *
 * 1. `SettingsSystemTab` sent `api.put('/auth/me', { unit_preference })`.
 *    Spec D9b removed that field from `UserSelfUpdate`, so the call is a 422
 *    today: the buttons show an error toast and revert, for every user. The
 *    frontend suite could not see it because `@/services/api` is mocked and a
 *    mock accepts any body. Units go to `PUT /auth/me/units` now, the one route
 *    that can express "clear all eleven override columns".
 * 2. For a client with no account the tab wrote the legacy `unit_preference`
 *    and `show_both_units` localStorage keys directly. `utils/unitPrefsStore.ts`
 *    ignores those the moment its own key exists, so the anonymous toggle
 *    changed nothing at all. A units choice goes through `setUnitPrefs`; the
 *    show-both modifier goes through `setShowBothUnits`, which is the only one
 *    that may withhold an unchosen set from storage.
 *
 * ★ THE HIGHLIGHT COMES FROM THE STORED TAG, THE SENTENCE FROM THE RESOLVED
 * SET, AND THAT DISAGREEMENT IS THE POINT. An account can hold
 * `unit_preference='metric'` with UK-imperial override columns: the retired
 * generic route wrote the preference and never cleared an override, and
 * migration 093 materialised all eleven for UK instances. Highlighting the
 * DERIVED tag instead would quietly relabel such an account "Custom" and hide
 * the contradiction; showing the recorded preset beside the units it actually
 * renders makes the highlighted button the lever that repairs it. Which is why
 * nothing on the write path takes a same-value early return.
 *
 * ★ THE INSTANCE-WIDE GALLON PANEL IS GONE (phase 4 task 5), and it is the one
 * control that never belonged here. Every other control on this card writes THIS
 * CLIENT's units; that panel wrote `imperial_gallon_standard`, an instance-wide
 * settings row, from a card any user can open, so it was the only control here a
 * non-admin could press and not save. `components/settings/InstanceUnitDefaultsCard.tsx`
 * writes the whole `default_unit_prefs` set instead, through these same eleven
 * controls, gated on `isAdmin || authMode === 'none'`. An account that wants a UK
 * gallon of its own sets `secondary_gallon` (or a `gal_uk` volume) under Custom,
 * which is where a per-account choice always belonged.
 *
 * ★ AND WHY A SHOW-BOTH TOGGLE CAN CHANGE `unit_preference`. `PUT
 * /auth/me/units` writes eleven explicit nulls for ANY preset, so echoing a
 * stale preset tag while the account resolves to something else would destroy
 * that set as a side effect of a display toggle. `unitsBodyFor` sends the
 * preset only when the resolved set IS that preset, and otherwise materialises
 * what the account already resolves to: a request that changes nothing the
 * account renders, and leaves the tag honest.
 */

import { useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { useAuth } from '@/contexts/AuthContext'
import { useUnitPreference } from '@/hooks/useUnitPreference'
import api from '@/services/api'
import {
  basePresetFor,
  presetTagFor,
  presetUnitsFor,
  type UnitPreference,
  type UnitSet,
} from '@/types/units'
import {
  getUnitPrefs,
  getUnitPrefsServerSnapshot,
  setShowBothUnits,
  setUnitPrefs,
  subscribeToUnitPrefs,
} from '@/utils/unitPrefsStore'
import { makeUnitFormat, resolvedUnitSummary } from '@/utils/unitFormat'
import { Toggle } from '../ui'
import UnitSetEditor, { type UnitSetSelection } from './UnitSetEditor'

/**
 * The fuel economy the show-both example is built from, in US MPG.
 *
 * ★ A ROUND NUMBER IN A UNIT, CONVERTED, rather than the canonical figure
 * spelled out. Writing 9.4160546 here reads as a conversion factor, and
 * `eslint`'s `no-restricted-syntax` guard says so: a high-precision literal in
 * a component is how this workstream's duplicated unit vocabularies started.
 * Twenty-five is a recognisable economy and the consumption adapter turns it
 * into canonical L/100km, so no factor is spelled here at all.
 *
 * It is a DISPLAY sample and converts like any other canonical value; nothing
 * is stored from it.
 */
const SHOW_BOTH_EXAMPLE_MPG = 25

/** The body `PUT /auth/me/units` accepts, in the two shapes it admits. */
type UnitsRequestBody = {
  unit_preference: UnitPreference
  units?: UnitSet
  show_both_units?: boolean
}

/**
 * Build a request that carries `showBoth` without disturbing the units.
 *
 * @param preference The preference the control currently shows.
 * @param units The set the client currently resolves to.
 * @param showBoth The display density to store.
 * @returns A body naming the preset only when the set really is that preset.
 */
function unitsBodyFor(
  preference: UnitPreference,
  units: UnitSet,
  showBoth: boolean
): UnitsRequestBody {
  if (preference !== 'custom' && presetTagFor(units) === preference) {
    return { unit_preference: preference, show_both_units: showBoth }
  }
  return { unit_preference: 'custom', units, show_both_units: showBoth }
}

export default function UnitPreferencesCard(): React.ReactElement {
  const { t } = useTranslation('settings')
  const { isAuthenticated, user: currentUser, refreshUser } = useAuth()
  const { units: resolvedUnits, showBoth } = useUnitPreference()
  const storedPrefs = useSyncExternalStore(
    subscribeToUnitPrefs,
    getUnitPrefs,
    getUnitPrefsServerSnapshot
  )

  // Optimistic overlays, so a control responds before the round trip lands.
  // Each is null while the stored value is authoritative.
  const [pendingPreference, setPendingPreference] = useState<UnitPreference | null>(null)
  const [pendingUnits, setPendingUnits] = useState<UnitSet | null>(null)
  const [pendingShowBoth, setPendingShowBoth] = useState<boolean | null>(null)
  const [saving, setSaving] = useState(false)

  // The preference this client has RECORDED. An account always has one; a
  // browser has one only once it has chosen, and the store derives that one
  // from its own set so it can never contradict it. With neither, the honest
  // label for the instance default is whatever that set matches.
  //
  // ★ A MIGRATED RECORD IS NOT A RECORDED PREFERENCE HERE, even though the
  // store derives a tag for it. That tag names the set the legacy keys produced,
  // and `useUnitPreference` rung 2 no longer renders that set: it keeps the
  // binary system and takes the gallon flavour from the instance. Reading the
  // stored tag anyway is how this card ends up highlighting "Imperial" over
  // `editorUnits` that say gal_uk, with the Custom grid hidden, which is the
  // exact dishonesty migration 093 fixed server-side. `presetTagFor` on the set
  // this client actually renders is the honest label for both.
  const storedPreference: UnitPreference | null = isAuthenticated
    ? (currentUser?.unit_preference ?? null)
    : storedPrefs?.units_are_migrated
      ? null
      : (storedPrefs?.unit_preference ?? null)
  const preference = pendingPreference ?? storedPreference ?? presetTagFor(resolvedUnits)
  const editorUnits = pendingUnits ?? resolvedUnits
  const showBothUnits = pendingShowBoth ?? showBoth

  // ★ The show-both example is COMPOSED from the reader's own set, not written
  // into the copy. The sentence used to read 'Display values in both imperial
  // and metric (e.g., "25 MPG (9.4 L/100km)")', which is wrong twice over
  // post-3b: the counterpart resolves per QUANTITY rather than per system, and
  // a reader whose consumption is L/100km was shown the reversed example. One
  // canonical figure through the resolved consumption formatter says what this
  // toggle will actually do to this account.
  const showBothExample = makeUnitFormat(editorUnits, true).consumption.format(
    // 25 US MPG as canonical L/100km, through the US preset's own consumption
    // adapter. The reader's set then renders it in whatever it holds.
    makeUnitFormat(presetUnitsFor('imperial', 'us')).consumption.toCanonical(
      SHOW_BOTH_EXAMPLE_MPG
    )
  )

  /** Persist a complete selection, wherever this client's preferences live. */
  const applySelection = async (selection: UnitSetSelection): Promise<void> => {
    setSaving(true)
    setPendingPreference(selection.unit_preference)
    setPendingUnits(selection.units)

    try {
      if (isAuthenticated) {
        await api.put(
          '/auth/me/units',
          selection.units === null
            ? { unit_preference: selection.unit_preference }
            : { unit_preference: selection.unit_preference, units: selection.units }
        )
        // `useUnitPreference` reads `user` from AuthContext, which changes only
        // when this reloads it. Without it the card saves and the screen does
        // not move.
        await refreshUser()
      } else {
        setUnitPrefs({
          // A preset expands to the set the ROUTE would resolve it to, so the
          // same button means the same thing with and without an account.
          units: selection.units ?? basePresetFor(selection.unit_preference),
          unit_preference: selection.unit_preference,
          show_both_units: showBothUnits,
        })
      }
      toast.success(t('preferences.unitSaved'))
    } catch {
      toast.error(t('preferences.unitError'))
      setPendingPreference(null)
      setPendingUnits(null)
    } finally {
      setSaving(false)
    }
  }

  const handleShowBothUnitsChange = async (next: boolean): Promise<void> => {
    setSaving(true)
    setPendingShowBoth(next)

    try {
      if (isAuthenticated) {
        await api.put('/auth/me/units', unitsBodyFor(preference, editorUnits, next))
        await refreshUser()
      } else {
        // ★ The store owns what happens to `units` here, and the card must
        // not pass a set through. A client that has never chosen holds
        // modifiers only, and writing the resolved set would invent an
        // explicit browser preference outranking `default_unit_prefs` forever.
        // A client whose units came from `migrateLegacy` holds a set built
        // from the module-load gallon guess, and persisting THAT as a side
        // effect of a display toggle freezes the guess just as permanently.
        // `setShowBothUnits` distinguishes the two; the card cannot.
        setShowBothUnits(next)
      }
      toast.success(t('preferences.displaySaved'))
    } catch {
      toast.error(t('preferences.displayError'))
      setPendingShowBoth(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    // Labelled as a region because the settings screen now carries TWO unit
    // editors: this one writes the CLIENT's units and
    // `InstanceUnitDefaultsCard` writes the instance default, and their controls
    // are deliberately identical. A reader (and a test) needs to be able to say
    // which set of Imperial / Metric / Custom buttons it means.
    <section aria-label={t('units.label')}>
      <UnitSetEditor
        preference={preference}
        units={editorUnits}
        busy={saving}
        onSelect={(selection) => void applySelection(selection)}
        description={
          <p className="mt-2 text-sm text-garage-text-muted">
            {t('units.resolvedDescription', { units: resolvedUnitSummary(editorUnits) })}
          </p>
        }
      />

      <div className="mt-4">
        <Toggle
          label={t('units.showBoth')}
          checked={showBothUnits}
          onChange={(next) => void handleShowBothUnitsChange(next)}
          disabled={saving}
        />
        <p className="mt-1 text-sm text-garage-text-muted">
          {t('units.showBothDescription', { example: showBothExample })}
        </p>
      </div>
    </section>
  )
}
