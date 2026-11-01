import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NumberInput } from '@/components/ui'
import { getActiveLocale } from '@/constants/i18n'
import { parseDecimalInput } from '@/utils/decimalInput'

interface SettingNumberInputProps {
  id: string
  /** The stored setting, as the settings form holds it: the API's own "2.5", never German text. */
  value: string
  /** Only ever called with a number that passes, written the way the API reads it ("2.5"). */
  onCommit: (value: string) => void
  /** Says whether this box holds something that can be saved, so the tab can refuse a save that can't. */
  onValidityChange: (id: string, valid: boolean) => void
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

/** The stored string as a number, or null when it isn't one. `Number('')` is 0, so blank is caught first. */
function storedNumber(value: string): number | null {
  if (value.trim() === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

/**
 * A number setting typed in the user's language. The settings tab saves every
 * change, so the box only hands a value up when it's left (blur) holding a
 * number in range. Until then, and while it's wrong, the stored value stays put
 * and the box tells the tab it can't be saved.
 *
 * Untouched, the box shows the stored value written in the active language
 * ("1,234" in de) and reads it as the API's number, so a language switch never
 * changes what it means. Once the user types, their text reads in their language.
 */
export function SettingNumberInput({
  id,
  value,
  onCommit,
  onValidityChange,
  min,
  max,
  integer = false,
  disabled,
  'aria-label': ariaLabel,
  className,
  size = 'sm',
}: SettingNumberInputProps) {
  const { t } = useTranslation('settings')
  // What the user typed, or null while the box shows the stored value.
  const [typed, setTyped] = useState<string | null>(null)
  // A reload or our own commit changes the stored value, and the box goes back to showing it.
  const [seen, setSeen] = useState(value)
  if (seen !== value) {
    setSeen(value)
    setTyped(null)
  }

  const locale = getActiveLocale()
  const stored = storedNumber(value)
  const text =
    typed ?? (stored === null ? value : new Intl.NumberFormat(locale, { useGrouping: false, maximumFractionDigits: 20 }).format(stored))
  const parsed = typed === null ? null : parseDecimalInput(typed, locale)
  const reading = typed === null ? stored : parsed?.kind === 'value' ? parsed.value : null
  const n =
    reading !== null && (!integer || Number.isInteger(reading)) && reading >= min && reading <= max ? reading : null

  const format = (x: number): string => new Intl.NumberFormat(locale).format(x)
  // A switched-off setting isn't in play, so it doesn't nag or hold up a save.
  const invalid = !disabled && n === null
  const error = invalid
    ? t(integer ? 'numberField.wholeBetween' : 'numberField.between', { min: format(min), max: format(max) })
    : undefined
  const errorId = `${id}-error`

  useEffect(() => {
    onValidityChange(id, !invalid)
  }, [id, invalid, onValidityChange])
  // Gone from the screen (another sub-tab, Advanced folded away), it can't hold up a save.
  useEffect(() => () => onValidityChange(id, true), [id, onValidityChange])

  return (
    <div className="flex flex-col">
      <NumberInput
        id={id}
        size={size}
        value={text}
        onChange={(e) => setTyped(e.target.value)}
        onBlur={() => {
          if (typed === null || n === null) return
          // Back to showing the stored value, which is now this one.
          setTyped(null)
          if (n !== stored) onCommit(String(n))
        }}
        disabled={disabled}
        invalid={invalid}
        aria-label={ariaLabel}
        aria-describedby={error ? errorId : undefined}
        className={className}
      />
      {error ? (
        <p id={errorId} role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  )
}
