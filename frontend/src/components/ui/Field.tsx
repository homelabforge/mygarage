import type { ReactNode } from 'react'
import type { FieldError } from 'react-hook-form'

interface FieldProps {
  /** Must match the control's id. Passed straight through — e2e and unit
   *  tests select controls by id (see standing instructions G6). */
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
  /** The control. Pass `aria-describedby` on it yourself — see the note below. */
  children: ReactNode
}

/**
 * Label + control + error, with the label↔control association intact.
 *
 * The required asterisk and the unit suffix are rendered as plain text INSIDE
 * the <label>, not as aria-hidden decorations or sibling elements. That is not
 * a style choice: VehicleEdit.test.tsx queries findByLabelText('edit.nickname *')
 * and findByLabelText('edit.defTankCapacity (L)'), so both strings are part of
 * the accessible name and must stay there.
 *
 * The hint and error nodes carry ids derived from the caller's id —
 * `${id}-hint` and `${id}-error` — but the CALLER is responsible for putting
 * them in the control's aria-describedby. Field does not attach the
 * association itself: `children` is opaque, so doing so would need
 * cloneElement, which silently does nothing when the child is a fragment, a
 * wrapper div, or a react-hook-form <Controller> render — all shapes this
 * codebase uses. A guaranteed id that the caller wires beats an association
 * that works in the demo and vanishes in the forms. Do not "fix" this by
 * computing the id and then dropping it — that would be worse than not
 * computing it at all.
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

  return (
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
  )
}
