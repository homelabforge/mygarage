// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type CalendarEvent = components['schemas']['CalendarEvent']
export type CalendarSummary = components['schemas']['CalendarSummary']
export type CalendarResponse = components['schemas']['CalendarResponse']

// ============================================================================
// Section B: Hand-maintained frontend-only types
// Derived from generated types for convenience in UI code.
// ============================================================================

export type EventType = CalendarEvent['type']
export type EventUrgency = CalendarEvent['urgency']
export type EventCategory = CalendarEvent['category']
