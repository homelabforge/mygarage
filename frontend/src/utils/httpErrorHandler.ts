/**
 * HTTP Error Handler Utility
 *
 * Maps HTTP status codes to user-friendly error messages.
 * Complements backend error handling standardization (v2.11.0).
 *
 * These functions run outside React (interceptors, service helpers, catch
 * blocks) so there is no component to call useTranslation from. They read the
 * i18next singleton defensively via `tSafe`, mirroring the pattern in
 * components/ErrorBoundary.tsx: a hard English default plus a try/catch, so an
 * error path can never itself throw or render a raw key.
 *
 * Backend-supplied `detail` text is passed through verbatim; only the generic
 * fallbacks below are translated.
 */

import { AxiosError } from 'axios'
import i18next from 'i18next'
import { parseValidationErrors, isValidationProblemArray } from './apiValidation'
import type { FieldProblem } from './apiValidation'

/**
 * Translate an error string without ever risking a throw.
 *
 * Error handling has to keep working when i18n is the thing that broke (not
 * initialised yet, namespace failed to load). An English message beats an
 * exception inside a catch block.
 */
function tSafe(key: string, fallback: string, values?: Record<string, unknown>): string {
  try {
    const value = i18next.t(key, { ns: 'common', defaultValue: fallback, ...values })
    return typeof value === 'string' && value.length > 0 ? value : fallback
  } catch {
    return fallback
  }
}

/** A translation key paired with its hard English fallback. */
type Message = readonly [key: string, fallback: string]

/**
 * HTTP status code to user-friendly message mapping
 */
const STATUS_MESSAGES: Record<number, Message> = {
  400: ['httpError.status.badRequest', 'Invalid request. Please check your input.'],
  401: ['httpError.status.unauthorized', 'Session expired. Please log in again.'],
  403: ['httpError.status.forbidden', 'You do not have permission to perform this action.'],
  404: ['httpError.status.notFound', 'The requested resource was not found.'],
  409: ['httpError.status.conflict', 'This action conflicts with existing data.'],
  422: ['httpError.status.unprocessable', 'The submitted data could not be processed.'],
  500: ['httpError.status.serverError', 'An unexpected server error occurred.'],
  502: ['httpError.status.badGateway', 'Server is temporarily unavailable. Please try again.'],
  503: [
    'httpError.status.serviceUnavailable',
    'Service temporarily unavailable. Please try again shortly.',
  ],
  504: ['httpError.status.gatewayTimeout', 'Request timed out. Please try again.'],
}

/**
 * Context-specific error messages for common operations
 */
const CONTEXT_MESSAGES: Record<string, Record<number, Message>> = {
  database: {
    409: ['httpError.database.conflict', 'A record with this data already exists.'],
    503: ['httpError.database.unavailable', 'Database temporarily unavailable. Please try again.'],
  },
  file: {
    403: ['httpError.file.forbidden', 'Permission denied. Cannot access file.'],
    404: ['httpError.file.notFound', 'File not found.'],
    500: ['httpError.file.serverError', 'Error accessing file.'],
  },
  external_api: {
    503: [
      'httpError.externalApi.unavailable',
      'External service unavailable. Please try again later.',
    ],
    504: ['httpError.externalApi.timeout', 'External service timed out. Please try again.'],
  },
}

const NETWORK_ERROR: Message = [
  'httpError.network',
  'Network error. Please check your connection.',
]
const GENERIC_ERROR: Message = ['httpError.generic', 'An error occurred.']
const UNEXPECTED_ERROR: Message = ['httpError.unexpected', 'An unexpected error occurred.']

/** Resolve a (key, English) pair through i18next. */
const translate = ([key, fallback]: Message): string => tSafe(key, fallback)

// parseApiError stamps what it returns. Handing a parsed error back in then
// gives the same object instead of parsing it as an unknown value, which threw
// away the status and detail and left "An unexpected error occurred".
const PARSED: unique symbol = Symbol('ParsedApiError')

export interface ParsedApiError {
  readonly [PARSED]: true
  /** HTTP status code (0 for network errors) */
  status: number
  /** User-friendly error message */
  message: string
  /** Raw error detail from API response */
  detail?: string
  /** Field-addressable problems from a 422. Empty for every other error. */
  fieldErrors: FieldProblem[]
  /** Whether this is a network/connectivity error */
  isNetworkError: boolean
  /** Whether this is a timeout error */
  isTimeout: boolean
  /** Whether user should retry the operation */
  shouldRetry: boolean
}

function isParsedApiError(error: unknown): error is ParsedApiError {
  return typeof error === 'object' && error !== null && PARSED in error
}

const stamp = (fields: Omit<ParsedApiError, typeof PARSED>): ParsedApiError => ({
  [PARSED]: true,
  ...fields,
})

/**
 * Parse an API error into a structured format with user-friendly message.
 *
 * @param error - The error from an API call (typically AxiosError)
 * @param context - Optional context for more specific messages ('database', 'file', 'external_api')
 * @returns Parsed error with user-friendly message
 */
export function parseApiError(error: unknown, context?: string): ParsedApiError {
  if (isParsedApiError(error)) return error

  // Handle Axios errors
  if (isAxiosError(error)) {
    // Network error (no response), so there's no body to read.
    if (!error.response) {
      return stamp({
        status: 0,
        message: translate(NETWORK_ERROR),
        detail: error.message,
        fieldErrors: [],
        isNetworkError: true,
        isTimeout: error.code === 'ECONNABORTED',
        shouldRetry: true,
      })
    }

    const status = error.response.status || 0
    // MyGarage's validation handler sends the 422 list as `details`; FastAPI's
    // default and a raised HTTPException use `detail`. Reading only `detail`
    // meant no 422 ever reached a field, so every form fell back to the banner.
    const data = error.response.data as { detail?: unknown; details?: unknown } | undefined
    const rawDetail = data?.detail ?? data?.details
    const fieldErrors = parseValidationErrors(rawDetail)
    // `detail` is human-facing text ONLY. A 422 sends an array, which must never
    // be stringified into a toast; fieldErrors carries that content. Falling
    // back to `error.message` here (axios's own "Request failed with status
    // code NNN") reintroduces the exact opaque string this release exists to
    // remove, and it's the ONLY body shape axios leaves reachable on the 11
    // `responseType: 'blob'` download sites (the error body arrives as an
    // unreadable Blob, so `.detail` never resolves there) plus any non-JSON
    // error page from a proxy. Leave `detail` undefined instead so
    // `getActionErrorMessage` falls through to its translated template.
    const detail = isValidationProblemArray(rawDetail)
      ? undefined
      : typeof rawDetail === 'string'
        ? rawDetail
        : undefined

    // Context-specific message if available, else the general status message
    const entry = CONTEXT_MESSAGES[context || '']?.[status] ?? STATUS_MESSAGES[status]
    let message = entry ? translate(entry) : translate(GENERIC_ERROR)

    // For 409 conflicts, use the API detail if it's more specific
    if (status === 409 && detail && !detail.includes('Exception')) {
      message = detail
    }

    return stamp({
      status,
      message,
      detail,
      fieldErrors,
      isNetworkError: false,
      isTimeout: status === 504,
      shouldRetry: [502, 503, 504].includes(status),
    })
  }

  // Handle standard Error objects
  if (error instanceof Error) {
    return stamp({
      status: 0,
      message: error.message || translate(GENERIC_ERROR),
      detail: error.message,
      fieldErrors: [],
      isNetworkError: false,
      isTimeout: false,
      shouldRetry: false,
    })
  }

  // Handle unknown errors
  return stamp({
    status: 0,
    message: translate(UNEXPECTED_ERROR),
    detail: String(error),
    fieldErrors: [],
    isNetworkError: false,
    isTimeout: false,
    shouldRetry: false,
  })
}

/**
 * Get a user-friendly error message from an API error.
 * Convenience function for simple error display.
 *
 * @param error - The error from an API call
 * @param fallbackMessage - Optional fallback message (already user-ready text)
 * @returns User-friendly error message
 */
export function getErrorMessage(error: unknown, fallbackMessage?: string): string {
  const parsed = parseApiError(error)
  return parsed.message || fallbackMessage || translate(GENERIC_ERROR)
}

/**
 * Get error message with action context.
 *
 * @param error - The error from an API call
 * @param action - The action being performed (e.g., 'save', 'delete', 'load')
 * @returns Contextual error message
 */
export function getActionErrorMessage(error: unknown, action: string): string {
  return actionErrorMessage(parseApiError(error), action)
}

/**
 * {@link getActionErrorMessage} for an error that's already parsed, so a form
 * that parsed it to place field errors doesn't parse it again for the banner.
 *
 * @param parsed - The parsed error, e.g. from `applyServerErrors`
 * @param action - The action being performed (e.g., 'save', 'delete', 'load')
 * @returns Contextual error message
 */
export function actionErrorMessage(parsed: ParsedApiError, action: string): string {
  const failed = (message: string): string =>
    tSafe('httpError.actionFailed', 'Failed to {{action}}. {{message}}', { action, message })

  // A 502/503/504 that says why keeps both the action and the reason: a
  // missing settings key, a busy vehicle lock, AutoRef down. Without one it's
  // the retry line. Status 0 retries too, but its detail is axios's own text.
  if (parsed.shouldRetry) {
    return failed(parsed.status !== 0 && parsed.detail ? parsed.detail : parsed.message)
  }

  // A backend detail is shown verbatim for these: a 404's "Vehicle not found"
  // beats the generic template, and login's "Incorrect username or password"
  // (401) or "User account is inactive" (403) must not read as "session
  // expired" on a typo.
  if ([400, 401, 403, 404, 422].includes(parsed.status) && parsed.detail) {
    return parsed.detail
  }

  // Without a detail only a 400 or 422 is about the input. A 401, 403 or 404
  // gets its status template below.
  if (parsed.status === 400 || parsed.status === 422) {
    return tSafe('httpError.actionFailedCheckInput', 'Failed to {{action}}. Please check your input.', {
      action,
    })
  }

  // For conflicts, the message is usually descriptive enough
  if (parsed.status === 409) {
    return parsed.message
  }

  return failed(parsed.message)
}

/**
 * Type guard for AxiosError
 */
function isAxiosError(error: unknown): error is AxiosError {
  return (
    typeof error === 'object' &&
    error !== null &&
    'isAxiosError' in error &&
    (error as AxiosError).isAxiosError === true
  )
}

/**
 * Determine if an error should trigger a retry attempt.
 *
 * @param error - The error from an API call
 * @returns Whether retry is recommended
 */
export function shouldRetryRequest(error: unknown): boolean {
  const parsed = parseApiError(error)
  return parsed.shouldRetry || parsed.isNetworkError
}

/**
 * Check if error is an authentication error requiring login.
 *
 * @param error - The error from an API call
 * @returns Whether this is an auth error
 */
export function isAuthError(error: unknown): boolean {
  if (isAxiosError(error)) {
    return error.response?.status === 401
  }
  return false
}

/**
 * Check if error is a permission/authorization error.
 *
 * @param error - The error from an API call
 * @returns Whether this is a permission error
 */
export function isPermissionError(error: unknown): boolean {
  if (isAxiosError(error)) {
    return error.response?.status === 403
  }
  return false
}
