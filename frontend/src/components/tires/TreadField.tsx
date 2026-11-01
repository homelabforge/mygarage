import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

import { useUnitFormat } from '../../hooks/useUnitFormat'
import { thirtySecondsFromDecimalInches } from '../../utils/treadEntry'
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

  return (
    <Field id={id} label={label} hint={hint}>
      <NumberInput
        id={id}
        value={value}
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
