import type { SelectHTMLAttributes } from 'react'
import { ChevronDown } from 'lucide-react'
import type { Size } from './types'

export interface SelectOption {
  value: string
  /** Already translated by the caller. If you are passing a translation KEY,
   *  name the field labelKey instead so validate-i18n-usage can see it (G5). */
  label: string
}

/**
 * `size` is omitted before being re-declared: the DOM `size` attribute on a
 * <select> is a `number` (visible row count), so extending without the Omit is
 * a TS2430 "interface incorrectly extends" error, the same defect as Input's.
 */
interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  options: SelectOption[]
  /** Renders one leading option. Counts toward option length. Selectable by
   *  default (not `disabled`) — every one of the 25 empty-placeholder
   *  `<option value="">` sites in this codebase is non-disabled, and at
   *  VehicleEdit.tsx / VehicleWizard.tsx that empty option is a real,
   *  re-selectable choice letting a user clear `fuel_type` back to null.
   *  Pass `placeholderDisabled` for the rare caller that truly wants an
   *  unselectable prompt. */
  placeholder?: string
  /** Makes the placeholder option `disabled`. Defaults to false — see
   *  `placeholder` above for why selectable is the correct default. */
  placeholderDisabled?: boolean
  size?: Size
  invalid?: boolean
}

const HEIGHT: Record<Size, string> = {
  sm: 'h-input-sm text-xs',
  md: 'h-input-md text-sm',
  lg: 'h-input-lg text-base',
}

/**
 * A native <select>. Not negotiable, and not a stylistic preference:
 *
 *  - 11 statements in e2e/i18n.spec.ts use locator('select'),
 *    option[value="pl"], selectOption() and toHaveValue()
 *  - 9 unit-test sites cast to HTMLSelectElement and fireEvent.change it
 *  - i18n.spec.ts:32,62 assert the select itself is VISIBLE, so the common
 *    "hidden native select behind a custom combobox" trick fails
 *  - three tests assert the option count is exactly options.length + 1, so
 *    no optgroup wrappers and no extra sentinel options
 *
 * The appearance-none + absolute chevron pattern is already the house style
 * (Dashboard.tsx) and is preserved.
 */
export default function Select({
  options,
  placeholder,
  placeholderDisabled = false,
  size = 'md',
  invalid = false,
  className = '',
  ...rest
}: SelectProps) {
  return (
    <div className="relative">
      <select
        aria-invalid={invalid || undefined}
        className={[
          'ui-focus-input ui-motion ui-disabled w-full cursor-pointer appearance-none rounded-control border bg-surface-2 pl-3 pr-10 text-text',
          HEIGHT[size],
          invalid ? 'border-danger' : 'border-border',
          className,
        ]
          .filter(Boolean)
          .join(' ')}
        {...rest}
      >
        {placeholder ? (
          // Non-disabled by default: a disabled <option> cannot be selected
          // by mouse or keyboard in any browser, which breaks the real
          // "clear this field back to empty" flow some callers rely on
          // (e.g. clearing fuel_type to null). Do not "helpfully" hardcode
          // `disabled` here again — see placeholderDisabled above.
          <option value="" disabled={placeholderDisabled}>
            {placeholder}
          </option>
        ) : null}
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <ChevronDown
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-mute"
      />
    </div>
  )
}
