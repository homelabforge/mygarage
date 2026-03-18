// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type Reminder = components['schemas']['ReminderResponse']
export type ReminderCreate = components['schemas']['ReminderCreate']
export type ReminderUpdate = components['schemas']['ReminderUpdate']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// ============================================================================

/** Derived from the ReminderCreate enum — keeps UI dropdowns in sync */
export type ReminderType = NonNullable<ReminderCreate['reminder_type']>

/** Backend uses plain str for status; narrow it for frontend UI logic */
export type ReminderStatus = 'pending' | 'done' | 'dismissed'

/** Frontend-only draft type used for inline reminder creation in forms */
export interface ReminderDraft extends ReminderCreate {
  enabled: boolean
}
