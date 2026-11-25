/**
 * The Imperial / Metric / Custom control and the eleven per-quantity selects.
 *
 * ★ WRITER-AGNOSTIC ON PURPOSE. It holds no state, performs no request and
 * knows nothing about accounts: it renders a preference plus a resolved set and
 * hands its caller a complete `UnitSetSelection`. `UnitPreferencesCard` supplies
 * the account writer (`PUT /auth/me/units`, or `unitPrefsStore` for a client
 * with no account); the instance-default settings row is a second writer for
 * the same controls. Before this file there was no reusable editor at all, only
 * one monolithic block inside `SettingsSystemTab`, so a second consumer had no
 * choice but to write a second set of eleven controls.
 *
 * ★ THE CONFIRMATION LIVES HERE, NOT IN THE CALLER. Choosing a preset CLEARS
 * every override column (D3), and v1's behaviour was the opposite: "toggling
 * back keeps your tuning". A user who learned that loses a set they expected to
 * be remembered, so the warning has to precede the write. It belongs to the
 * control rather than to the writer because both writers clear the same way,
 * and a confirmation the second one forgot would be invisible.
 *
 * ★ AND IT NAMES THE GALLON CONSEQUENCE. Both canonical presets are written
 * with `secondary_gallon='us'` (`app/constants/units.py`), so a UK-gallon client
 * choosing Imperial lands on US gallons: a 20 percent move in every volume and
 * every MPG, from a button labelled with the system it is already on. R4.
 *
 * ★ `compact` IS THE QUICK SETTINGS LAYOUT. A 400 px drawer cannot take the
 * page's: eleven selects left open push every other preference out of sight,
 * so under Custom they sit in an accordion, closed until asked for. The page
 * asks through the app's confirm dialog; compact keeps the question in place
 * under the buttons (`InlineConfirm`), by choice.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Ruler } from 'lucide-react'
import {
  UNIT_FIELD_NAMES,
  UNIT_OPTION_LABELS,
  unitOptionsFor,
  withUnitField,
  type UnitPreference,
  type UnitSet,
} from '@/types/units'
import { gallonStandardFor } from '@/utils/publicUnitDefaults'
import { Select, useConfirm } from '../ui'
import { segmentClass } from './choiceStyles'
import InlineConfirm from './InlineConfirm'

/**
 * A complete unit selection, in the shape `PUT /auth/me/units` accepts.
 *
 * The union IS the backend invariant
 * (`UnitPreferenceUpdate.units_present_exactly_when_custom`): a preset carries
 * no set, because the route writes eleven explicit nulls for it, and `custom`
 * carries all eleven, because a partial custom leaves some quantities resolving
 * from the base preset. Spelling it as a union means a caller cannot build the
 * rejected combinations at all.
 */
export type UnitSetSelection =
  | { unit_preference: 'imperial' | 'metric'; units: null }
  | { unit_preference: 'custom'; units: UnitSet }

export interface UnitSetEditorProps {
  /** The preference to highlight. The caller decides where it comes from. */
  preference: UnitPreference
  /** The set the eleven controls show, and what Custom materialises from. */
  units: UnitSet
  /** Rendered between the tri-state control and the Custom grid. */
  description?: React.ReactNode
  /** Disables every control, for a write in flight. */
  busy?: boolean
  /** Distinguishes the control ids when two editors share one screen. */
  idPrefix?: string
  /** The Quick Settings layout: Custom as an accordion, the confirmation in place. */
  compact?: boolean
  /** Called with a complete selection, after any confirmation it requires. */
  onSelect: (selection: UnitSetSelection) => void
}

/**
 * The two presets, in the order the retired toggle showed them.
 *
 * ★ THE KEY IS ON A `labelKey` FIELD, and that spelling is load-bearing.
 * `scripts/validate-i18n-usage.ts` reads a translate call whose argument is a
 * bare literal, and a module-level string const, and neither form covers a key
 * looked up out of a record. Holding these two in a plain
 * `Record<Preset, string>` put them outside every i18n gate this repo has, and
 * the vitest mock returns the key unchanged so a component test cannot see a
 * missing one either: the pair would have been checked by nothing at all.
 * `labelKey` is one of the field names that script does read.
 *
 * (This paragraph deliberately does not SPELL that call. The script's scan is a
 * regex over the file's text with no comment handling, so prose quoting the
 * call form is read as a call: the first draft of this comment failed the gate
 * on a key named by the ellipsis inside it.)
 */
const PRESETS = [
  { value: 'imperial', labelKey: 'units.imperial' },
  { value: 'metric', labelKey: 'units.metric' },
] as const satisfies readonly { value: 'imperial' | 'metric'; labelKey: string }[]

/** One tri-state preset button's identity. */
type PresetChoice = (typeof PRESETS)[number]

export default function UnitSetEditor({
  preference,
  units,
  description,
  busy = false,
  idPrefix = 'unit',
  compact = false,
  onSelect,
}: UnitSetEditorProps): React.ReactElement {
  const { t } = useTranslation('settings')
  const confirm = useConfirm()
  // Compact only: the page asks through the confirm dialog instead.
  const [pendingPreset, setPendingPreset] = useState<PresetChoice | null>(null)
  // Compact only. Closed on every mount, even for a Custom account: the drawer
  // opens for many reasons and editing eleven units is the rarest of them.
  const [customOpen, setCustomOpen] = useState(false)

  // Control SELECTION, not a conversion: the caller's stored preference beside
  // a button's own value. No literal, so the units gate has nothing to report
  // here and no pragma is claimed; the sentence naming this client's actual
  // units is `description` below.
  const isChosen = (candidate: UnitPreference): boolean => preference === candidate

  // D4b: which gallon this client's set currently means, read from the set
  // rather than from the binary system, so the warning fires for a metric
  // account whose secondary gallon is UK too.
  //
  // units-exempt(compare): WARNING COPY, keyed on which button was pressed. There is no quantity here and nothing canonical to convert: the comparison names the preset the user is moving TO, and the gallon half beside it is read from the resolved set through `gallonStandardFor` rather than from a collapsed system. Kind-scoped, so a comparison of an actual quantity added to this line would still be reported.
  const losesUkGallon = (preset: PresetChoice): boolean => preset.value === 'imperial' && gallonStandardFor(units) === 'uk'

  const consequence = (preset: PresetChoice): React.ReactElement => (
    <div className="space-y-2">
      <p className="text-sm text-garage-text-muted">{t('units.presetConfirmMessage')}</p>
      {losesUkGallon(preset) && <p className="text-sm text-warning">{t('units.presetConfirmGallon')}</p>}
    </div>
  )

  const chooseQuantity = (field: keyof UnitSet, token: string): void => {
    const next = withUnitField(units, field, token)
    // A token outside the quantity's vocabulary cannot come from these options;
    // refusing it rather than casting keeps the one cast in `withUnitField`.
    if (next === null) return
    onSelect({ unit_preference: 'custom', units: next })
  }

  // ★ NO SAME-VALUE EARLY RETURN, anywhere on this path. An account can be
  // TAGGED with a preset while resolving to something else entirely, and
  // pressing the highlighted button is that user's only way to clear the
  // overrides masking it. Skipping the request because "nothing changed"
  // preserves the exact defect this phase exists to remove.
  const confirmPreset = (): void => {
    if (pendingPreset === null) return
    onSelect({ unit_preference: pendingPreset.value, units: null })
    setPendingPreset(null)
  }

  const askPreset = async (preset: PresetChoice): Promise<void> => {
    const ok = await confirm({
      message: t('units.presetConfirmTitle', { preset: t(preset.labelKey) }),
      detail: consequence(preset),
      confirmLabel: t('units.presetConfirmAction'),
      tone: 'default',
    })
    if (ok) onSelect({ unit_preference: preset.value, units: null })
  }

  const segment = (
    chosen: boolean,
    label: string,
    onClick: () => void
  ): React.ReactElement => (
    <button
      key={label}
      type="button"
      aria-pressed={chosen}
      onClick={onClick}
      disabled={busy}
      className={segmentClass(chosen, busy, compact ? 'sm' : 'md')}
    >
      {!compact && <Ruler className="w-5 h-5" />}
      <span className="font-medium">{label}</span>
    </button>
  )

  // The eleven selects, built only when Custom is the choice. Columns follow
  // the EDITOR's width (the `@container` on the root below), not the
  // screen's: a screen breakpoint put two columns into the 400 px drawer on
  // every desktop.
  const renderCustomGrid = (): React.ReactElement => (
    <>
      <p className="mb-3 text-sm text-garage-text-muted">{t('units.customDescription')}</p>
      <div className="grid grid-cols-1 @md:grid-cols-2 gap-3">
        {/* Every quantity `UnitSet` declares, derived from the vocabulary
            rather than listed, so a twelfth cannot be silently omitted.
            `secondary_gallon` is included with show-both OFF (D4b): the
            widget endpoints always emit MPG and something has to say which
            gallon that MPG means. */}
        {UNIT_FIELD_NAMES.map((field) => (
          <div key={field}>
            <label
              htmlFor={`${idPrefix}-${field}`}
              className="block text-xs text-garage-text-muted mb-1"
            >
              {t(UNIT_OPTION_LABELS[field].labelKey)}
            </label>
            <Select
              id={`${idPrefix}-${field}`}
              value={units[field]}
              disabled={busy}
              onChange={(e) => chooseQuantity(field, e.target.value)}
              // D10: the NAME is translated and only the symbol is a
              // literal, so this renders "Kilopascals (kPa)" and never the
              // stored token `kpa`.
              options={unitOptionsFor(field).map((option) => ({
                value: option.value,
                label: t(option.labelKey),
              }))}
            />
          </div>
        ))}
      </div>
    </>
  )

  const choosePreset = (preset: PresetChoice): void => {
    if (compact) setPendingPreset(preset)
    else void askPreset(preset)
  }

  return (
    <div className="@container">
      <label
        className={compact ? 'ui-eyebrow mb-2 block' : 'block text-sm font-medium text-garage-text mb-3'}
      >
        {t('units.label')}
      </label>
      <div className={compact ? 'flex gap-2' : 'flex flex-col gap-3 @md:flex-row'}>
        {PRESETS.map((preset) =>
          segment(isChosen(preset.value), t(preset.labelKey), () => choosePreset(preset))
        )}
        {segment(isChosen('custom'), t('units.custom'), () => {
          onSelect({ unit_preference: 'custom', units })
          setCustomOpen(true)
        })}
      </div>

      {compact && pendingPreset !== null && (
        <InlineConfirm
          id={`${idPrefix}-preset-confirm`}
          title={t('units.presetConfirmTitle', { preset: t(pendingPreset.labelKey) })}
          confirmLabel={t('units.presetConfirmAction')}
          onConfirm={confirmPreset}
          onCancel={() => setPendingPreset(null)}
        >
          {consequence(pendingPreset)}
        </InlineConfirm>
      )}

      {description}

      {isChosen('custom') &&
        (compact ? (
          <div className="mt-3">
            <button
              type="button"
              aria-expanded={customOpen}
              aria-controls={`${idPrefix}-custom-panel`}
              onClick={() => setCustomOpen((open) => !open)}
              className="ui-focus-ring flex w-full items-center justify-between rounded-lg border border-garage-border bg-garage-bg px-3 py-2 text-sm font-medium text-garage-text hover:bg-garage-surface transition-colors"
            >
              {t('units.customToggle')}
              <ChevronDown
                aria-hidden="true"
                className={`h-4 w-4 transition-transform duration-200 motion-reduce:transition-none ${
                  customOpen ? 'rotate-180' : ''
                }`}
              />
            </button>
            {/* Opens downward and closes back up: the row animates from 0fr to
                1fr. `inert` while closed, so the hidden selects take no focus
                and are not read out. */}
            <div
              id={`${idPrefix}-custom-panel`}
              className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${
                customOpen ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
              }`}
            >
              <div className="overflow-hidden" inert={!customOpen}>
                <div className="pt-3">{renderCustomGrid()}</div>
              </div>
            </div>
          </div>
        ) : (
          <div className="mt-4">{renderCustomGrid()}</div>
        ))}
    </div>
  )
}
