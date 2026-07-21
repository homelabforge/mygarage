import type { InputHTMLAttributes, ReactNode } from 'react'
import type { Size } from './types'

/**
 * `size` and `prefix` must be omitted from the DOM attribute set before they
 * can be re-declared. Both already exist there with incompatible types — DOM
 * `size` is `number` (the visible character width of a text input) and
 * `prefix` is the RDFa `string` attribute — so extending without the Omit is
 * TS2430 twice over ("interface incorrectly extends"), not a warning.
 */
interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size' | 'prefix'> {
  size?: Size
  /** Monospace the value. The prototype monospaces every numeric, currency
   *  and date input; ~60-80 call sites want this. */
  mono?: boolean
  invalid?: boolean
  /** Leading adornment, e.g. a currency symbol. */
  prefix?: ReactNode
  suffix?: ReactNode
}

const HEIGHT: Record<Size, string> = {
  sm: 'h-input-sm text-xs',
  md: 'h-input-md text-sm',
  lg: 'h-input-lg text-base',
}

/**
 * The bare control. `Field` owns the label — this never renders one, and
 * never substitutes a floating label: `getByPlaceholderText` is used in 12
 * places and a floating label would consume the placeholder (G6).
 *
 * `type` is forwarded untouched because implicit roles hang off it:
 * type="number" ⇒ spinbutton (5 tests), type="text" ⇒ textbox (11 tests).
 */
export default function Input({
  size = 'md',
  mono = false,
  invalid = false,
  prefix,
  suffix,
  className = '',
  ...rest
}: InputProps) {
  const control = (
    <input
      aria-invalid={invalid || undefined}
      className={[
        'ui-focus-input ui-motion ui-disabled w-full rounded-control border bg-surface-2 px-3 text-text placeholder-text-faint',
        HEIGHT[size],
        invalid ? 'border-danger' : 'border-border',
        mono ? 'font-mono tabular-nums' : '',
        prefix ? 'pl-7' : '',
        suffix ? 'pr-7' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      {...rest}
    />
  )

  if (!prefix && !suffix) return control

  return (
    <div className="relative">
      {prefix ? (
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-text-mute">
          {prefix}
        </span>
      ) : null}
      {control}
      {suffix ? (
        <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-sm text-text-mute">
          {suffix}
        </span>
      ) : null}
    </div>
  )
}
