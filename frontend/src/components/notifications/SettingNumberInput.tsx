import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NumberInput } from '@/components/ui'
import { getActiveLocale } from '@/constants/i18n'
import { parseDecimalInput } from '@/utils/decimalInput'

interface SettingNumberInputProps {
  id: string
  /** The stored setting, as the settings form holds it. */
  value: string
  /** Only ever called with a number that passes, written the way the API reads it ("2.5"). */
  onCommit: (value: string) => void
  min: number
  max: number
  /** Whole numbers only. */
  integer?: boolean
  disabled?: boolean
  'aria-label'?: string
  className?: string
  /** Defaults to the compact row size. */
  size?: 'sm' | 'md'
}

/**
 * A number setting typed in the user's language. The settings tab saves every
 * change, so text that isn't a number, isn't whole, or is out of range stays
 * in the box with a message and never goes up to be saved.
 */
export function SettingNumberInput({
  id,
  value,
  onCommit,
  min,
  max,
  integer = false,
  disabled,
  'aria-label': ariaLabel,
  className,
  size = 'sm',
}: SettingNumberInputProps) {
  const { t } = useTranslation('settings')
  const [text, setText] = useState(value)
  // The stored value this text stands for, so a reload can replace the text
  // but our own "2,5" -> "2.5" commit doesn't.
  const [shown, setShown] = useState(value)
  if (shown !== value) {
    setShown(value)
    setText(value)
  }

  const read = (raw: string): number | null => {
    const parsed = parseDecimalInput(raw, getActiveLocale())
    if (parsed.kind !== 'value') return null
    const n = parsed.value
    if (integer && !Number.isInteger(n)) return null
    return n >= min && n <= max ? n : null
  }

  const format = (n: number): string => new Intl.NumberFormat(getActiveLocale()).format(n)
  // A switched-off setting isn't in play, so it doesn't nag.
  const error =
    !disabled && read(text) === null
      ? t(integer ? 'numberField.wholeBetween' : 'numberField.between', { min: format(min), max: format(max) })
      : undefined
  const errorId = `${id}-error`

  return (
    <div className="flex flex-col">
      <NumberInput
        id={id}
        size={size}
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          const n = read(e.target.value)
          if (n === null) return
          setShown(String(n))
          onCommit(String(n))
        }}
        disabled={disabled}
        invalid={error !== undefined}
        aria-label={ariaLabel}
        aria-describedby={error ? errorId : undefined}
        className={className}
        parsedOnChange
      />
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  )
}
