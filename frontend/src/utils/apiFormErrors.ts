import type { FieldValues, UseFormSetError, Path } from 'react-hook-form'
import { parseApiError } from './httpErrorHandler'
import type { ParsedApiError } from './httpErrorHandler'
import type { FieldProblem } from './apiValidation'

interface FieldSplit {
  /** Problems attached to a control the user can see. */
  attached: FieldProblem[]
  /** Problems with nowhere to go: the caller MUST surface these itself. */
  unhandled: FieldProblem[]
}

export interface ApplyResult extends FieldSplit {
  /**
   * The failed request, parsed once. Build the banner from it with
   * `actionErrorMessage` rather than parsing the error a second time.
   */
  parsed: ParsedApiError
}

/**
 * Split a failed request's field problems into ones matching a rendered
 * control ("attached") vs everything else ("unhandled"). Shared by the two
 * split-application paths below (react-hook-form's `setFieldError` and a
 * controlled form's own `Record<field, message>` state), so both use the
 * exact same matching rule instead of two independently-maintained copies.
 *
 * Matching is exact-string on the field name. Nested react-hook-form paths
 * like `items.0.qty` will only attach if the caller enumerates that exact
 * expanded path; otherwise they route to `unhandled` for the caller's toast.
 */
function splitFieldProblems(fieldErrors: FieldProblem[], knownFields: readonly string[]): FieldSplit {
  const attached: FieldProblem[] = []
  const unhandled: FieldProblem[] = []
  for (const problem of fieldErrors) {
    if (knownFields.includes(problem.field)) {
      attached.push(problem)
    } else {
      unhandled.push(problem)
    }
  }
  return { attached, unhandled }
}

/**
 * Attach a failed request's field problems to the controls that caused them.
 *
 * Only fields the form actually registers are attached. A problem addressed to
 * anything else (a query parameter, a field this form does not render) is
 * returned as `unhandled`, because react-hook-form silently keeps an error for
 * an unregistered name and the user would never see it.
 *
 * [rev2] Callers must surface `unhandled`. The previous boolean return caused a
 * mixed payload to suppress the toast and lose the unmapped problem entirely.
 */
export function applyServerErrors<T extends FieldValues>(
  setFieldError: UseFormSetError<T>,
  error: unknown,
  knownFields: ReadonlyArray<Path<T>>
): ApplyResult {
  const parsed = parseApiError(error)
  const result = splitFieldProblems(parsed.fieldErrors, knownFields)
  for (const problem of result.attached) {
    setFieldError(problem.field as Path<T>, { type: 'server', message: problem.message })
  }
  return { ...result, parsed }
}

/**
 * Same split as {@link applyServerErrors}, for the handful of controlled
 * (non-react-hook-form) forms that track field errors as a plain
 * `Record<field, message>` instead of calling an RHF `setFieldError`.
 *
 * The caller owns showing the banner: `attached.length === 0 ||
 * unhandled.length > 0` mirrors the RHF-side gate: a 422 that
 * matches nothing, or leaves a problem unmapped, must still surface
 * SOMETHING, or it writes to state, renders nothing, and suppresses the
 * banner too (the exact silent-failure bug this function exists to close).
 */
export function applyControlledFieldErrors(
  error: unknown,
  knownFields: readonly string[]
): ApplyResult & { errorsByField: Record<string, string> } {
  const parsed = parseApiError(error)
  const result = splitFieldProblems(parsed.fieldErrors, knownFields)
  const errorsByField = Object.fromEntries(result.attached.map((p) => [p.field, p.message]))
  return { ...result, parsed, errorsByField }
}

/**
 * Drop one field's error from a controlled form's error map, for its change
 * handler: once the user edits the field, the old message is stale. Use it as
 * `setFieldErrors((prev) => withoutFieldError(prev, key))`.
 *
 * Hands back the same object when the map has no entry for the key, so React
 * skips the re-render on every keystroke of a field that was fine all along.
 */
export function withoutFieldError<T extends Partial<Record<string, string>>>(errors: T, key: string): T {
  if (!Object.hasOwn(errors, key)) return errors
  const next = { ...errors }
  delete next[key]
  return next
}
