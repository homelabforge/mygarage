// ============================================================================
// Section A: Generated type aliases from OpenAPI schema
// Source of truth: backend Pydantic models -> openapi.json -> api.generated.ts
// Run `bun run generate:api` after backend schema changes and commit both files.
// ============================================================================

import type { components } from './api.generated'

export type AddressBookEntry = components['schemas']['AddressBookEntryResponse']
export type AddressBookEntryCreate = components['schemas']['AddressBookEntryCreate']
export type AddressBookEntryUpdate = components['schemas']['AddressBookEntryUpdate']
export type AddressBookListResponse = components['schemas']['AddressBookListResponse']
