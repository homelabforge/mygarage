import type { ReactNode } from 'react'
import type { FieldError } from 'react-hook-form'
import { FieldContext } from './fieldContext'

interface FieldProps {
  /** Must match the control's id. Passed straight through, since e2e and
   *  unit tests select controls by id. */
  id: string
  /** Already translated by the caller. */
  label: string
  required?: boolean
  /** Unit suffix, rendered inside the label as "(L)". */
  unit?: string
  /** Rendered as `<p id={`${id}-error`} role="alert">`. */
  error?: string | FieldError
  /** Rendered as `<p id={`${id}-hint`}>`. */
  hint?: string
  /** The control. If it is a ui primitive (Input/Select/Textarea) the hint↔
   *  error association is wired automatically via FieldContext (see below). */
  children: ReactNode
}

/**
 * Label + control + error, with the label↔control association intact.
 *
 * The required asterisk and the unit suffix are rendered as plain text INSIDE
 * the <label>, not as aria-hidden decorations or sibling elements. That is not
 * a style choice: VehicleEditDrawer.test.tsx queries findByLabelText('edit.nickname *')
 * and findByLabelText('edit.defTankCapacity (L)'), so both strings are part of
 * the accessible name and must stay there.
 *
 * The hint and error nodes carry ids derived from the caller's id:
 * `${id}-hint` and `${id}-error`. Field publishes those ids on FieldContext,
 * and the ui primitives (Input/Select/Textarea) read them via
 * useFieldDescribedBy and merge them into their own aria-describedby. This wires
 * the association WITHOUT cloneElement, which silently does nothing when the
 * child is a fragment, a wrapper div, or a react-hook-form <Controller> render,
 * all shapes this codebase uses. A control that is not a ui primitive (a raw
 * <input>, a custom component) sees the ids on the context and can still opt in;
 * if it does nothing, it simply keeps the previous behaviour (ids present in the
 * DOM, association left to the caller).
 */
export default function Field({
  id,
  label,
  required = false,
  unit,
  error,
  hint,
  children,
}: FieldProps) {
  const message = typeof error === 'string' ? error : error?.message

  const describedBy =
    [hint ? `${id}-hint` : null, message ? `${id}-error` : null].filter(Boolean).join(' ') ||
    undefined

  return (
    <FieldContext.Provider value={{ describedBy }}>
      <div className="mb-4">
        <label htmlFor={id} className="mb-1 block text-sm font-medium text-text">
          {label}
          {required ? ' *' : ''}
          {unit ? ` (${unit})` : ''}
        </label>
        {children}
        {hint ? (
          <p id={`${id}-hint`} className="mt-1 text-xs text-text-mute">
            {hint}
          </p>
        ) : null}
        {message ? (
          <p id={`${id}-error`} role="alert" className="mt-1 text-xs text-danger">
            {message}
          </p>
        ) : null}
      </div>
    </FieldContext.Provider>
  )
}
