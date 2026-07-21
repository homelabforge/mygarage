import { useId, type InputHTMLAttributes } from 'react'

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  /** Already translated by the caller. */
  label: string
}

/**
 * Checkbox = picking items from a set (allowed file types, POI categories).
 * Toggle = a single on/off setting. That distinction is the prototype's
 * (handoff README §Controls & Conventions).
 *
 * `id` is forwarded verbatim: one_time_visit, poi_gas_station and is_active
 * are located by document.getElementById in three unit-test files, and
 * AddressBook.test.tsx:18 documents that getByLabelText would NOT match.
 */
export default function Checkbox({ id, label, disabled, className = '', ...rest }: CheckboxProps) {
  const fallbackId = useId()
  const inputId = id ?? fallbackId

  return (
    <label
      htmlFor={inputId}
      className={`flex items-center gap-3 text-sm text-text ${
        disabled ? '' : 'cursor-pointer'
      }`}
    >
      <input
        id={inputId}
        type="checkbox"
        disabled={disabled}
        className={`ui-focus-ring ui-disabled h-4 w-4 rounded-[4px] border-border bg-surface-2 accent-(--accent-solid) ${className}`}
        {...rest}
      />
      {label}
    </label>
  )
}
