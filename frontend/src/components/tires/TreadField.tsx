import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useUnitFormat } from '../../hooks/useUnitFormat'
import { thirtySecondsFromDecimalInches } from '../../utils/treadEntry'
import { Field, Input } from '../ui'

interface TreadFieldProps {
  id: string
  label: string
  /** The field's text, in the user's tread unit. */
  value: string
  onChange: (next: string) => void
}

/**
 * A tread depth input that reads a decimal-inch entry in thirty-seconds.
 *
 * On blur, `0.346` in a `/32 in` field becomes `11`, and the hint says what it
 * was converted from, so the rewrite is visible rather than silent. Every tread
 * input on the tire screens renders through this, Add and Edit Tire, Log
 * Reading and the reading editor, so no one of them is left reading a gauge's
 * decimal as thirty-seconds. Save paths still run `normaliseTreadEntry`
 * themselves: a value typed and saved without a blur never reaches this
 * handler.
 */
export default function TreadField({ id, label, value, onChange }: TreadFieldProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  /* What the last blur converted, kept until the next keystroke so the hint
     describes the value on screen and never one the user has since replaced. */
  const [convertedFrom, setConvertedFrom] = useState<string | null>(null)

  const inThirtySeconds = u.tread.unit === 'in32'
  const hint =
    convertedFrom !== null
      ? t('tireList.treadConverted', { inches: convertedFrom, thirtySeconds: value })
      : inThirtySeconds
        ? t('tireList.treadDecimalHint')
        : undefined

  return (
    <Field id={id} label={label} hint={hint}>
      <Input
        id={id}
        type="number"
        step={u.tread.step}
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
        }}
      />
    </Field>
  )
}
