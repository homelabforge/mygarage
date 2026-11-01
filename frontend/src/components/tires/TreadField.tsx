import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

import { useUnitFormat } from '../../hooks/useUnitFormat'
import { getActiveLocale } from '../../constants/i18n'
import { parseDecimalInput } from '../../utils/decimalInput'
import { gaugeDecimal, thirtySecondsFromDecimalInches } from '../../utils/treadEntry'
import { Field, NumberInput } from '../ui'

interface TreadFieldProps {
  id: string
  label: string
  /** The field's text, in the reader's tread unit. */
  value: string
  onChange: (next: string) => void
  /** A blur converted the entry. Drop the field's origin: the 32nds it now holds are a new measurement. */
  onConverted: () => void
  /** The standing inches hint under a /32 in field. Off for the minimum, which nobody reads off a gauge. */
  gaugeHint?: boolean
}

/**
 * A tread input that reads a gauge's decimal inches in a /32 in field.
 *
 * On blur, 0.346 becomes 11, the hint says what it converted, and `onConverted`
 * fires so the form stops treating that 11 as the one it seeded. Save paths read
 * through `canonicalFromTreadField`, for a value saved without a blur.
 */
export default function TreadField({
  id,
  label,
  value,
  onChange,
  onConverted,
  gaugeHint = true,
}: TreadFieldProps): ReactElement {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  // What the last blur converted, dropped on the next keystroke.
  const [convertedFrom, setConvertedFrom] = useState<string | null>(null)

  const hint =
    convertedFrom !== null
      ? t('tireList.treadConverted', { inches: convertedFrom, thirtySeconds: value })
      : u.tread.unit === 'in32' && gaugeHint
        ? t('tireList.treadDecimalHint')
        : undefined

  // The box's own "Read as" hint would read a German 0.346 as 346. A /32 field
  // reads it as gauge inches, so say that instead, and only where the two differ.
  const gauge = u.tread.unit === 'in32' ? gaugeDecimal(value) : null
  const plain = gauge === null ? null : parseDecimalInput(value, getActiveLocale())
  const gaugeReadAs =
    gauge !== null && plain?.kind === 'value' && plain.value !== gauge
      ? t('common:numberInput.readAs', {
          value: new Intl.NumberFormat(getActiveLocale(), { maximumFractionDigits: 20 }).format(gauge),
        })
      : undefined

  return (
    <Field id={id} label={label} hint={hint}>
      <NumberInput
        id={id}
        value={value}
        ambiguityHint={gaugeReadAs}
        onChange={(e) => {
          setConvertedFrom(null)
          onChange(e.target.value)
        }}
        onBlur={() => {
          const converted = thirtySecondsFromDecimalInches(value, u.tread)
          if (converted === null) return
          setConvertedFrom(value)
          onChange(converted)
          onConverted()
        }}
      />
    </Field>
  )
}
