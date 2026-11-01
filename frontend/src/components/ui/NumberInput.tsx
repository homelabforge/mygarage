import { useId, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, ComponentProps, FocusEvent } from 'react'
import { useTranslation } from 'react-i18next'
import type {
  FieldPath,
  FieldValues,
  RegisterOptions,
  UseFormRegister,
  UseFormRegisterReturn,
} from 'react-hook-form'
import Input from './Input'
import { getActiveLocale } from '@/constants/i18n'
import { localeDecimalSeparator, parseDecimalInput } from '@/utils/decimalInput'
import { formatAtPrecision } from '@/utils/unitFormat'
import { INVALID_NUMBER } from '@/schemas/shared'

interface NumberInputProps extends Omit<ComponentProps<typeof Input>, 'type' | 'inputMode'> {
  /** Overrides the hint NumberInput works out for itself from what the user typed. */
  ambiguityHint?: string
  /**
   * A controlled caller that parses each change and keeps the number, instead
   * of parsing its text at save. The hint then reads in the locale of that change.
   */
  parsedOnChange?: boolean
}

/** How often a visible hint checks the form hasn't overwritten the field. Exported for tests. */
export const OVERWRITE_CHECK_MS = 250

/**
 * The value the user's text was read as, but only when that's the 1000x
 * reading: one separator and three digits after it, and this locale writes its
 * decimal point with the other character, so it was taken as grouping.
 */
function groupingReading(text: string, locale: string): number | null {
  const result = parseDecimalInput(text, locale)
  // Zero reads the same either way, so there's nothing to warn about.
  if (result.kind !== 'value' || !result.ambiguous || result.value === 0) return null
  // The ambiguous shape has exactly one separator, so whichever is in the text is it.
  const separator = text.includes(',') ? ',' : '.'
  return localeDecimalSeparator(locale) === separator ? null : result.value
}

/**
 * Register a numeric field so the raw text is parsed with the locale-aware rule
 * instead of the browser's `valueAsNumber`.
 *
 * `valueAsNumber` accepts only a dot and yields NaN otherwise, which the schema
 * layer swallowed as "empty". This routes the field through parseDecimalInput
 * and emits a sentinel the schema rejects.
 *
 * `options` passes through any other RHF rules — SupplyHistoryModal keeps
 * `required` inside `register` (no zod resolver on those two inline forms),
 * and dropping it would delete real validation.
 *
 * `min`/`max` are excluded from `options` on purpose, not just left
 * undocumented: RHF's native min/max check (`validateField`) coerces the
 * field value with unary `+` to compare it, which throws a TypeError on the
 * `INVALID_NUMBER` symbol this function can emit for unparseable text — this
 * is exactly what happened to SupplyHistoryModal's `quantity`/`total_cost`
 * fields before they were moved to an equivalent `validate` function instead.
 * On a resolver-based form `min`/`max` here would be silently inert anyway
 * (RHF skips `validateField` entirely whenever a `resolver` is configured),
 * so there's no case where passing them helps — better a compile error than
 * either dead code or a stack trace.
 */
export function registerDecimal<T extends FieldValues>(
  register: UseFormRegister<T>,
  name: FieldPath<T>,
  options?: Omit<RegisterOptions<T, FieldPath<T>>, 'setValueAs' | 'valueAsNumber' | 'valueAsDate' | 'min' | 'max'>
): UseFormRegisterReturn {
  return register(name, {
    ...options,
    setValueAs: (raw: unknown) => {
      // Edit mode supplies a number from defaultValues; never re-parse it as text.
      if (typeof raw === 'number') return raw
      const result = parseDecimalInput(String(raw ?? ''), getActiveLocale())
      if (result.kind === 'empty') return undefined
      if (result.kind === 'invalid') return INVALID_NUMBER
      // RHF keeps this until the next change or blur, read in the locale of that moment.
      // NumberInput's hint stamps the same moments so it reads the text the same way.
      return result.value
    },
  })
}

/**
 * Text input for decimals.
 *
 * Deliberately NOT `type="number"`: that clears its own value when the content
 * is unparseable, so the user's separator never reaches the handler.
 * `inputMode="decimal"` keeps the numeric keypad on mobile.
 *
 * When what the user typed got the grouping reading ("1,234" in en is 1234,
 * not 1.234) it says so underneath, so a 1000x odometer is caught before save.
 * It keys off the typed text, so a default nobody touched stays quiet.
 *
 * The hint reads the text the way its owner does. A registerDecimal field is
 * parsed by RHF on change and blur and cached, so a language switch after
 * typing doesn't move it: the hint keeps the locale of that last change or
 * blur. A controlled caller holds the text and parses it at save (or render)
 * in whatever language is active, so its hint follows the active language,
 * unless it says `parsedOnChange`, which reads like registerDecimal minus the blur.
 */
export default function NumberInput({
  mono = true,
  ambiguityHint,
  parsedOnChange = false,
  id,
  'aria-describedby': ariaDescribedBy,
  onChange,
  onBlur,
  ...rest
}: NumberInputProps) {
  const { t } = useTranslation('common')
  const fallbackId = useId()
  // What was typed, and the locale it was typed (or last blurred) under.
  const [typed, setTyped] = useState<{ text: string; locale: string } | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const controlled = rest.value !== undefined

  const handleChange = (event: ChangeEvent<HTMLInputElement>): void => {
    // Grabbed from the event so the caller's ref (RHF's register) goes through untouched.
    inputRef.current = event.currentTarget
    setTyped({ text: event.currentTarget.value, locale: getActiveLocale() })
    onChange?.(event)
  }

  const handleBlur = (event: FocusEvent<HTMLInputElement>): void => {
    // RHF re-reads the box on blur too, so restamp with the locale it'll use.
    if (!controlled) {
      const locale = getActiveLocale()
      setTyped(prev => (prev === null || prev.locale === locale ? prev : { ...prev, locale }))
    }
    onBlur?.(event)
  }

  // A controlled caller's value wins, but only while it's still what was typed.
  const current = typed !== null && (!controlled || rest.value === typed.text) ? typed : null
  // RHF (or a parsedOnChange caller) already parsed it under the stamp; anyone else parses in today's language.
  const reading = current?.text
    ? groupingReading(current.text, controlled && !parsedOnChange ? getActiveLocale() : current.locale)
    : null
  const hint =
    ambiguityHint ??
    (reading === null ? undefined : t('numberInput.readAs', { value: formatAtPrecision(reading, 0) }))
  const hintId = hint ? `${id ?? fallbackId}-ambiguity` : undefined

  // Forms write fields too (reset, a recalculated cost), and RHF's setValue
  // fires no event and often no render here. So while a hint is up, check the
  // box still holds what was typed: now, and every OVERWRITE_CHECK_MS.
  useLayoutEffect(() => {
    const input = inputRef.current
    if (reading === null || input === null) return
    const dropIfOverwritten = (): void => {
      if (input.value !== typed?.text) setTyped(null)
    }
    dropIfOverwritten()
    const timer = window.setInterval(dropIfOverwritten, OVERWRITE_CHECK_MS)
    return () => window.clearInterval(timer)
  })

  return (
    <>
      <Input
        id={id}
        type="text"
        inputMode="decimal"
        mono={mono}
        aria-describedby={[ariaDescribedBy, hintId].filter(Boolean).join(' ') || undefined}
        onChange={handleChange}
        onBlur={handleBlur}
        {...rest}
      />
      {hint ? (
        <p id={hintId} className="mt-1 text-xs text-text-mute">
          {hint}
        </p>
      ) : null}
    </>
  )
}
