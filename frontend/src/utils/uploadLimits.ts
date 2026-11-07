/**
 * The document upload cap the server enforces (`MYGARAGE_MAX_DOCUMENT_SIZE_MB`),
 * served read-only with the public settings so any user's form checks the
 * real limit (B5-7). Documents and window stickers share it.
 */
export const DOCUMENT_MAX_BYTES_KEY = 'document_upload_max_bytes'

/** The cap in bytes, or null when the public settings didn't say (the server still checks). */
export function documentMaxBytes(values: Readonly<Record<string, string | null | undefined>>): number | null {
  const bytes = Number(values[DOCUMENT_MAX_BYTES_KEY])
  return Number.isFinite(bytes) && bytes > 0 ? bytes : null
}

/** Whole megabytes for the message, as the server's own limit is set. */
export function megabytes(bytes: number): number {
  return Math.round(bytes / (1024 * 1024))
}
