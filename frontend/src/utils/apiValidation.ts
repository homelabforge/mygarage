/**
 * FastAPI reports request validation failures as a 422 whose `detail` is an
 * ARRAY of problems, not a string:
 *
 *   [{ type: 'decimal_parsing', loc: ['body','premium_amount'], msg: '…', input: '528,25' }]
 *
 * `httpErrorHandler` historically typed `detail` as `string`, so this shape was
 * invisible and every form reported a bare "Request failed with status code 422".
 */

export interface ValidationProblem {
  type: string
  loc: (string | number)[]
  msg: string
  input?: unknown
}

export interface FieldProblem {
  /** react-hook-form field path, e.g. `premium_amount` or `items.0.qty`. */
  field: string
  message: string
  type: string
}

/** A loc is a path, so only names and list indexes belong in it. */
const isLocSegment = (segment: unknown): segment is string | number =>
  typeof segment === 'string' || typeof segment === 'number'

export function isValidationProblemArray(detail: unknown): detail is ValidationProblem[] {
  // An empty list has no problem to show, so it's not one of these.
  return (
    Array.isArray(detail) &&
    detail.length > 0 &&
    detail.every(
      p =>
        typeof p === 'object' &&
        p !== null &&
        Array.isArray((p as ValidationProblem).loc) &&
        (p as ValidationProblem).loc.every(isLocSegment) &&
        typeof (p as ValidationProblem).msg === 'string' &&
        typeof (p as ValidationProblem).type === 'string'
    )
  )
}

/**
 * Flatten problems into field-addressable form.
 *
 * A leading `body` segment is dropped so the remainder matches the form field
 * name. Any other prefix (`query`, `path`, `header`) is KEPT so it can never be
 * mistaken for a form field, and will fall through to a toast.
 */
export function parseValidationErrors(detail: unknown): FieldProblem[] {
  if (!isValidationProblemArray(detail)) return []

  const problems: FieldProblem[] = []
  for (const p of detail) {
    const segments = p.loc[0] === 'body' ? p.loc.slice(1) : p.loc
    if (segments.length === 0) continue
    problems.push({ field: segments.join('.'), message: p.msg, type: p.type })
  }
  return problems
}
