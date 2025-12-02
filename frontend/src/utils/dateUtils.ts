/**
 * Date utility functions to handle date formatting without timezone issues
 */

/**
 * Format a date string for display without timezone conversion.
 * Appends T00:00:00 to force local timezone interpretation.
 *
 * @param dateString - ISO date string (YYYY-MM-DD)
 * @param options - Intl.DateTimeFormatOptions for formatting
 * @returns Formatted date string
 */
export function formatDateForDisplay(
  dateString: string,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }
): string {
  // Parse date without timezone conversion by appending T00:00:00
  const date = new Date(dateString + 'T00:00:00')
  return date.toLocaleDateString('en-US', options)
}

/**
 * Format a date string for input[type="date"] without timezone issues.
 * Ensures the date is in YYYY-MM-DD format without timezone conversion.
 *
 * @param dateString - Date string in various formats
 * @returns Date string in YYYY-MM-DD format
 */
export function formatDateForInput(dateString?: string | null): string {
  if (!dateString) {
    const now = new Date()
    const year = now.getFullYear()
    const month = String(now.getMonth() + 1).padStart(2, '0')
    const day = String(now.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  // If it's already in YYYY-MM-DD format, return as-is
  if (/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
    return dateString
  }

  // Otherwise parse and format without timezone conversion
  const date = new Date(dateString + 'T00:00:00')
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
