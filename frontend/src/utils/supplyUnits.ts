/**
 * Supplies are measured in litres or in whole items, and D8 exempts the quart
 * conversion below from the adapter table.
 *
 * ★ RULING R3, and the premise all three comparisons below rest on. D8 exempts
 * the quart CONVERSION; it says nothing about whether these comparisons may
 * read a collapsed `system`, so each one is ruled separately at its own site.
 *
 * The premise they share: THESE THREE LEGS TRACK `unit_preference`, NOT THE
 * RESOLVED VOLUME, AND THAT IS DELIBERATE. D8 gave supplies a vocabulary of
 * `qt` and `L`, and `UnitSet` cannot express it: `UnitSet.volume` is
 * `L | gal_uk | gal_us` and there is no quart token anywhere in the resolved
 * set. So there is no `units` field for these comparisons to read. Supplies are
 * the one quantity in the app with no resolved source of truth, because the
 * spec created a display unit the vocabulary never got.
 *
 * That is the same root as the UK-quart defect recorded on `supplyUnitLabel`
 * below, and both wait on the same D8 amendment: give supplies a resolved
 * token, and these three legs get something to read and the factor gets a
 * flavour at the same time. Until then a preference is the only signal there is.
 *
 * ★ AN EARLIER VERSION OF THIS BLOCK CLAIMED `system === binarySystemFor(units.volume)`
 * ON ALL FOUR RUNGS. THAT IS FALSE, and the account it is false for is one the
 * product creates on purpose. `useUnitPreference.ts:systemFor` consults
 * `resolved_units` ONLY when `unit_preference === 'custom'`; for `'metric'` and
 * `'imperial'` it returns the preference verbatim while `units` stays the fully
 * resolved set. `PUT /auth/me` writes the preference and never clears an
 * override column (`SettingsSystemTab.tsx` says so at length), and
 * `backend/app/utils/unit_resolution.py:resolve_units` applies the eleven
 * override columns on top of the preset for EVERY account, `custom` or not. So
 * `{preference:'metric', overrides: UK imperial}` reaches this file as
 * `system='metric'` with `units.volume='gal_uk'`.
 *
 * ★ NAMING THE POPULATION THIS EXEMPTION KNOWINGLY LEAVES INCOHERENT, because a
 * ruling that implies no such account exists is worse than no ruling. That
 * account renders gallons, miles and Fahrenheit on every other screen and
 * LITRES here. Measured, not reasoned: label `'L'` where the resolved token
 * says `'qt'`, one stored litre displayed as `1` where the resolved token says
 * `1.0567`. It is NOT data corruption: label, read and write all follow
 * `system` together, so a round trip is exact and nothing stored is wrong. It
 * is a real user-visible inconsistency, and it is the price of D8's missing
 * token rather than of these comparisons.
 *
 * The old premise also failed to distinguish this file from the phase's
 * signature defect, so state the distinction properly: `toCanonicalKm` was
 * wrong because it applied a VOLUME collapse to DISTANCE, a quantity the
 * resolved set could have answered for. Supplies have nothing to ask.
 *
 * ★ WHAT THE THREE DECLARATION PRAGMAS BELOW ACTUALLY COVER, measured rather
 * than described. Task 8 made the units gate's binary-conversion vocabulary
 * tree-wide, which made these three exports visible for the first time, and the
 * enumeration with the pragmas removed is 15 occurrences under 11 keys across 5
 * files: SupplyHistoryModal.tsx 7, ServiceVisitForm.tsx 3, SuppliesUsedTab.tsx
 * 2, Supplies.tsx 2, SupplyUsedPicker.tsx 1. Reproduce it rather than trusting
 * this line: delete the three pragmas and run `bun run
 * scripts/validate-units.ts --report`.
 *
 * Two of those fifteen are `ServiceVisitForm.tsx:249` and `:344`, where the
 * helper is passed to `convertSupplyUsages` as a VALUE rather than called, and
 * the second is the write path. The gate could not see either until task 8
 * added the value-reference half of that leg, which it did because a count in
 * its own report failed to survive being checked against the enumerator. Read
 * `isValueReference` in `scripts/validate-units.ts` before assuming a helper
 * that is never called by name here is not reaching storage.
 *
 * ★ The TYPE is not exempt, and used to be declared here as a second
 * `'metric' | 'imperial'` union structurally identical to `utils/units.ts`'s.
 * TypeScript compares unions structurally, so `tsc` could never see the two
 * drift apart, and they did: when the API-level preference union was widened
 * to admit `'custom'`, one copy was updated and this one silently was not.
 * There is one `UnitSystem` declaration in the codebase now and one place to
 * import it from, so widening it reaches every consumer of both. It is
 * deliberately NOT re-exported from here: a second import path is how the
 * second declaration would come back.
 */
import type { UnitSystem } from './units'

export type SupplyUnitType = 'volume' | 'count'

const L_PER_QUART = 0.946352946

/**
 * Convert a canonical value (L for volume, count for count) to the user's display unit.
 *
 * R3 ruling, READ leg: EXEMPT, because there is nothing to migrate TO. The
 * branch selects between quarts and litres, and `UnitSet` holds no quart token,
 * so `units` cannot answer the question this line asks. Rewriting it as
 * `units.volume === 'L'` would not be a migration to the resolved set: it would
 * be a second guess at the same missing token, and it would silently change
 * which unit the incoherent account named in the header sees.
 */
// units-exempt(binary-conversion): R3 read leg, at the DECLARATION. Task 8 made the binary-conversion vocabulary tree-wide, so this export and its call sites became visible together; the ruling below is one ruling and it belongs here rather than copied onto each of the fifteen sites in five files. Owner: deferred, pending the D8 amendment. Expires with the read leg's own pragma.
export function canonicalToDisplay(
  value: number,
  unitType: SupplyUnitType,
  system: UnitSystem,
): number {
  // units-exempt(compare): R3 read leg; D8 gave supplies a qt/L vocabulary UnitSet cannot express, so `units` holds nothing this branch could read. Owner: deferred, pending the D8 amendment. Expires when UnitSet carries a supplies token, which is the same amendment the UK-quart defect on supplyUnitLabel waits on.
  if (unitType === 'count' || system === 'metric') return value
  return value / L_PER_QUART // liters → quarts
}

/**
 * Convert a user-entered display value back to canonical (L / count).
 *
 * R3 ruling, WRITE leg: EXEMPT, and exempt as a PAIR with `canonicalToDisplay`
 * rather than on its own. This is the only function here that reaches storage,
 * so it is the one a wrong answer would make permanent. It is exempt for
 * exactly the reason the read leg is, and its condition is character-identical
 * on purpose: that identity is what keeps the incoherent account in the header
 * merely inconsistent instead of corrupted, because the value written and the
 * value read back are conditioned on the same signal. Migrating either leg
 * alone is the real hazard: a stored litre read back through a
 * differently-conditioned display is a silent 5.7 percent per round trip, so if
 * these ever move they move in the same commit.
 */
// units-exempt(binary-conversion): R3 write leg, at the DECLARATION. This is the export that reaches storage, so its call sites are the ones a wrong answer would make permanent; they are exempt for the reason the read leg is and move with it, never alone. Owner: deferred, pending the D8 amendment.
export function displayToCanonical(
  value: number,
  unitType: SupplyUnitType,
  system: UnitSystem,
): number {
  // units-exempt(compare): R3 write leg; same reason as the read leg and character-identical to it on purpose, which is what keeps the round trip exact. Owner: deferred, pending the D8 amendment. Expires with the read leg, in the same commit, never alone.
  if (unitType === 'count' || system === 'metric') return value
  return value * L_PER_QUART // quarts → liters
}

/**
 * Unit label for display.
 *
 * R3 ruling, LABEL leg: EXEMPT for the header's reason, with one defect
 * recorded that migrating this comparison would NOT fix.
 *
 * ★ DEFERRED DEFECT, 20.1 percent, UK instances. `L_PER_QUART` is the US liquid
 * quart (0.946352946); the UK quart is 4.54609/4 = 1.1365225. A UK user
 * entering one quart of oil stores 0.946 L where they meant 1.137, the same
 * magnitude and the same shape as defect L1.
 *
 * Rewriting `system === 'imperial'` as `units.volume !== 'L'` selects the same
 * branch and yields the same label, so the comparison is not what makes that
 * user wrong. The CONSTANT is. And the resolved set is not as silent as an
 * earlier draft of this comment claimed: `UnitSet.secondary_gallon` is
 * `'us' | 'uk'` for every account, and `UnitConverter.LITERS_PER_VOLUME_UNIT`
 * already holds both gallons, so a correct quart is derivable today as
 * `LITERS_PER_VOLUME_UNIT[gal_x] / 4` with no new vocabulary. What actually
 * blocks the fix is D8's silence about which quart it meant, plus the stored
 * data: changing the factor re-interprets every supply quantity already written
 * on a UK instance, and no column records which quart a row was written in.
 * That is a spec amendment and a data decision, not a refactor.
 */
// units-exempt(binary-conversion): R3 label leg, at the DECLARATION. Seven of the fifteen sites are this one, measured with the three pragmas off rather than counted by hand, and every one of them is a label beside a value the two legs above already conditioned on the same signal. Owner: deferred, pending the D8 amendment, which also owns the 20.1 percent UK-quart defect in the docstring above.
export function supplyUnitLabel(unitType: SupplyUnitType, system: UnitSystem): string {
  if (unitType === 'count') return ''
  // units-exempt(compare): R3 label leg; the qt/L choice is not in UnitSet, so migrating this comparison changes nothing. Owner: deferred, pending the D8 amendment, which also owns the 20.1 percent UK-quart defect in the docstring above. Expires when D8 says which quart it meant.
  return system === 'imperial' ? 'qt' : 'L'
}
