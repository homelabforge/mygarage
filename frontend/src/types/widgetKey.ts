/**
 * Widget API key types — thin wrappers over the generated OpenAPI schemas.
 * Importing from api.generated.ts keeps backend/frontend shapes locked in sync.
 */

import type { components } from './api.generated'

export type WidgetKeySummary = components['schemas']['WidgetKeySummary']
export type WidgetKeyCreated = components['schemas']['WidgetKeyCreated']
export type WidgetKeyList = components['schemas']['WidgetKeyList']
export type WidgetKeyCreate = components['schemas']['WidgetKeyCreate']
export type WidgetKeyScope = WidgetKeyCreate['scope']
