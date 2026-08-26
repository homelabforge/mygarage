/**
 * Tire types, re-exported from the generated OpenAPI schema.
 *
 * Previously hand-maintained, with the same invisible-drift problem as
 * AuthContext's local User interface. Converted before the tire mount-periods
 * work adds sets, periods, and derived fields to these shapes.
 */

import type { components } from './api.generated'

export type Tire = components['schemas']['TireResponse']
export type TireReading = components['schemas']['TireReadingResponse']
export type TireListResponse = components['schemas']['TireListResponse']
export type TireCreate = components['schemas']['TireCreate']
export type TireUpdate = components['schemas']['TireUpdate']
export type TireReadingCreate = components['schemas']['TireReadingCreate']

export type TirePosition = Tire['position']
