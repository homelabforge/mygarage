/**
 * Brake types (#202), re-exported from the generated OpenAPI schema.
 */

import type { components } from './api.generated'

export type BrakeOverview = components['schemas']['BrakeOverviewResponse']
export type BrakeAxle = components['schemas']['BrakeAxleResponse']
export type BrakeCorner = components['schemas']['BrakeCornerResponse']
export type BrakeMeasurement = components['schemas']['BrakeMeasurementResponse']
export type BrakeJob = components['schemas']['BrakeJobResponse']
export type BrakeAxleUpdate = components['schemas']['BrakeAxleUpdate']
export type BrakeMeasurementBatchCreate = components['schemas']['BrakeMeasurementBatchCreate']
export type BrakeMeasurementCorner = components['schemas']['BrakeMeasurementCorner']
export type BrakeMeasurementUpdate = components['schemas']['BrakeMeasurementUpdate']
export type BrakeJobCreate = components['schemas']['BrakeJobCreate']
export type BrakeJobUpdate = components['schemas']['BrakeJobUpdate']

export type BrakePosition = BrakeCorner['position']
export type BrakeAxleName = BrakeAxle['axle']
export type BrakeType = BrakeAxle['brake_type']
export type BrakeSurface = NonNullable<BrakeJob['surface']>

/** The four corners, front to back, left to right. Brakes have no spare. */
export const BRAKE_POSITIONS: BrakePosition[] = ['FL', 'FR', 'RL', 'RR']

/** Which axle a corner is on. */
export const AXLE_OF: Record<BrakePosition, BrakeAxleName> = {
  FL: 'front',
  FR: 'front',
  RL: 'rear',
  RR: 'rear',
}
