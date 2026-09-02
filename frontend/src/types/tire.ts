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

/**
 * Where a tire is mounted, or `null`/`undefined` when it is in storage.
 *
 * Nullable since v3.3.0: "off the vehicle" is a real state a tire spends half
 * the year in, and the old schema could not express it -- a seasonal set had
 * to be deleted and re-entered every six months, taking its readings with it.
 */
export type TirePosition = Tire['position']

/**
 * A position a tire can actually be mounted at.
 *
 * `TirePosition` includes null, which is right for a tire's CURRENT position
 * and wrong everywhere a corner is being named: a label map, a dropdown, the
 * target of a mount. Keeping them separate is what stops `labels[null]` from
 * type-checking.
 */
export type MountedPosition = NonNullable<TirePosition>

export type TireMountPeriod = components['schemas']['MountPeriodResponse']
export type TireMountRequest = components['schemas']['TireMountRequest']
export type TireDismountRequest = components['schemas']['TireDismountRequest']
export type TireCreateAndMountRequest = components['schemas']['TireCreateAndMountRequest']
export type TireRotationRequest = components['schemas']['TireRotationRequest']

/** Why `distance_km` is or is not available. Exhaustive; see the backend enum. */
export type DistanceStatus =
  | 'complete'
  | 'incomplete'
  | 'nothing_bounded'
  | 'no_periods'
  | 'spare_only'
  | 'odometer_rollback'

/** Why a wear projection is or is not available. Exhaustive. */
export type WearStatus =
  | 'projected'
  | 'at_or_below_minimum'
  | 'no_minimum_set'
  | 'insufficient_readings'
  | 'no_reading_odometers'
  | 'tread_not_decreasing'
  | 'no_distance_on_tire'
  | 'unverified_mount_history'
