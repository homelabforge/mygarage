/**
 * HTTP Error Handler Utility
 *
 * Maps HTTP status codes to user-friendly error messages.
 * Complements backend error handling standardization (v2.11.0).
 */

import { AxiosError } from 'axios'

/**
 * HTTP status code to user-friendly message mapping
 */
const STATUS_MESSAGES: Record<number, string> = {
  400: 'Invalid request. Please check your input.',
  401: 'Session expired. Please log in again.',
  403: 'You do not have permission to perform this action.',
  404: 'The requested resource was not found.',
  409: 'This action conflicts with existing data.',
  422: 'The submitted data could not be processed.',
  500: 'An unexpected server error occurred.',
  502: 'Server is temporarily unavailable. Please try again.',
  503: 'Service temporarily unavailable. Please try again shortly.',
  504: 'Request timed out. Please try again.',
}

/**
 * Context-specific error messages for common operations
 */
const CONTEXT_MESSAGES: Record<string, Record<number, string>> = {
  database: {
    409: 'A record with this data already exists.',
    503: 'Database temporarily unavailable. Please try again.',
  },
  file: {
    403: 'Permission denied. Cannot access file.',
    404: 'File not found.',
    500: 'Error accessing file.',
  },
  external_api: {
    503: 'External service unavailable. Please try again later.',
    504: 'External service timed out. Please try again.',
  },
}

export interface ParsedApiError {
  /** HTTP status code (0 for network errors) */
  status: number
  /** User-friendly error message */
  message: string
  /** Raw error detail from API response */
  detail?: string
  /** Whether this is a network/connectivity error */
  isNetworkError: boolean
  /** Whether this is a timeout error */
  isTimeout: boolean
  /** Whether user should retry the operation */
  shouldRetry: boolean
}

/**
 * Parse an API error into a structured format with user-friendly message.
 *
 * @param error - The error from an API call (typically AxiosError)
 * @param context - Optional context for more specific messages ('database', 'file', 'external_api')
 * @returns Parsed error with user-friendly message
 */
export function parseApiError(error: unknown, context?: string): ParsedApiError {
  // Handle Axios errors
  if (isAxiosError(error)) {
    const status = error.response?.status || 0
    const detail = (error.response?.data as { detail?: string })?.detail || error.message

    // Network error (no response)
    if (!error.response) {
      return {
        status: 0,
        message: 'Network error. Please check your connection.',
        detail: error.message,
        isNetworkError: true,
        isTimeout: error.code === 'ECONNABORTED',
        shouldRetry: true,
      }
    }

    // Get context-specific message if available
    let message = CONTEXT_MESSAGES[context || '']?.[status]

    // Fall back to general status message
    if (!message) {
      message = STATUS_MESSAGES[status] || 'An error occurred.'
    }

    // For 409 conflicts, use the API detail if it's more specific
    if (status === 409 && detail && !detail.includes('Exception')) {
      message = detail
    }

    return {
      status,
      message,
      detail,
      isNetworkError: false,
      isTimeout: status === 504,
      shouldRetry: [502, 503, 504].includes(status),
    }
  }

  // Handle standard Error objects
  if (error instanceof Error) {
    return {
      status: 0,
      message: error.message || 'An error occurred.',
      detail: error.message,
      isNetworkError: false,
      isTimeout: false,
      shouldRetry: false,
    }
  }

  // Handle unknown errors
  return {
    status: 0,
    message: 'An unexpected error occurred.',
    detail: String(error),
    isNetworkError: false,
    isTimeout: false,
    shouldRetry: false,
  }
}

/**
 * Get a user-friendly error message from an API error.
 * Convenience function for simple error display.
 *
 * @param error - The error from an API call
 * @param fallbackMessage - Optional fallback message
 * @returns User-friendly error message
 */
export function getErrorMessage(error: unknown, fallbackMessage = 'An error occurred'): string {
  const parsed = parseApiError(error)
  return parsed.message || fallbackMessage
}

/**
 * Get error message with action context.
 *
 * @param error - The error from an API call
 * @param action - The action being performed (e.g., 'save', 'delete', 'load')
 * @returns Contextual error message
 */
export function getActionErrorMessage(error: unknown, action: string): string {
  const parsed = parseApiError(error)

  // For timeouts and service unavailable, add retry suggestion
  if (parsed.shouldRetry) {
    return `Failed to ${action}. ${parsed.message}`
  }

  // For validation errors, show the detail
  if (parsed.status === 400 || parsed.status === 422) {
    return parsed.detail || `Failed to ${action}. Please check your input.`
  }

  // For conflicts, the message is usually descriptive enough
  if (parsed.status === 409) {
    return parsed.message
  }

  return `Failed to ${action}. ${parsed.message}`
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
