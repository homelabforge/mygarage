/**
 * Shared fixtures for the generated API shapes.
 *
 * `UserResponse` carries seventeen required fields since per-quantity unit
 * preferences landed, so every test that mocks an account would otherwise
 * hand-roll them and drift apart. Building them in one place means a new
 * required field breaks this file, loudly, instead of quietly leaving each
 * call site to guess.
 *
 * The two presets mirror `backend/app/constants/units.py`; keep them in step.
 */

import type { components } from '@/types/api.generated'

export type User = components['schemas']['UserResponse']
export type UnitSet = components['schemas']['UnitSet']
export type VehicleStatistics = components['schemas']['VehicleStatistics']
export type VehicleDetailStats = components['schemas']['VehicleDetailStats']

/** The metric preset, as `resolve_units` returns it. */
export const METRIC_UNITS: UnitSet = {
  distance: 'km',
  speed: 'kmh',
  length: 'm',
  volume: 'L',
  consumption: 'l_100km',
  pressure: 'kpa',
  temperature: 'c',
  mass: 'kg',
  torque: 'nm',
  tread: 'mm',
  secondary_gallon: 'us',
}

/** The imperial (US) preset, as `resolve_units` returns it. */
export const IMPERIAL_UNITS: UnitSet = {
  distance: 'mi',
  speed: 'mph',
  length: 'ft',
  volume: 'gal_us',
  consumption: 'mpg_us',
  pressure: 'psi',
  temperature: 'f',
  mass: 'lb',
  torque: 'lbft',
  tread: 'in32',
  secondary_gallon: 'us',
}

/**
 * The UK-imperial preset, as `resolve_units` returns it.
 *
 * Mirrors `app/utils/default_unit_prefs.py`'s `UK_IMPERIAL_PRESET`: the
 * imperial preset with volume, consumption and secondary_gallon replaced. It is
 * the set that separates a per-user gallon from the instance-wide one, so
 * anything asserting defect L1 is fixed uses it.
 */
export const UK_IMPERIAL_UNITS: UnitSet = {
  ...IMPERIAL_UNITS,
  volume: 'gal_uk',
  consumption: 'mpg_uk',
  secondary_gallon: 'uk',
}

/**
 * Build a resolved unit set, metric unless overridden.
 *
 * @param overrides Fields to replace on the metric preset.
 * @returns A complete `UnitSet`.
 */
export function makeUnitSet(overrides: Partial<UnitSet> = {}): UnitSet {
  return { ...METRIC_UNITS, ...overrides }
}

/**
 * Build a plausible non-admin account.
 *
 * Timestamps are fixed literals on purpose: a relative date in a fixture is a
 * calendar bomb, and one has already broken a release here.
 *
 * @param overrides Fields to replace on the default account.
 * @returns A complete `UserResponse`.
 */
export function makeUser(overrides: Partial<User> = {}): User {
  return {
    id: 1,
    username: 'testuser',
    email: 'test@test.com',
    is_active: true,
    is_admin: false,
    country: null,
    inspection_auto_schedule: true,
    auth_method: 'local',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_login: null,
    language: 'en',
    currency_code: 'USD',
    time_format: '12h',
    dashboard_sort: 'name',
    mobile_quick_entry_enabled: true,
    show_both_units: false,
    show_on_family_dashboard: false,
    family_dashboard_order: 0,
    unit_preference: 'imperial',
    resolved_units: IMPERIAL_UNITS,
    ...overrides,
  }
}

/**
 * Build a dashboard card's stats: a distance-tracked car with no records and
 * nothing due, so a test names only what it is about.
 *
 * @param overrides Fields to replace on the default card.
 * @returns A complete `VehicleStatistics`.
 */
export function makeVehicleStatistics(
  overrides: Partial<VehicleStatistics> = {},
): VehicleStatistics {
  return {
    vin: 'TEST00000000000001',
    year: 2024,
    make: 'Toyota',
    model: 'Camry',
    vehicle_type: 'Car',
    main_photo_url: null,
    usage_unit: 'distance',
    distance_unit: null,
    current_hours: null,
    latest_hours: null,
    average_l_per_hr: null,
    average_cost_per_hr: null,
    secondary_usage_enabled: false,
    total_service_records: 0,
    total_fuel_records: 0,
    total_odometer_records: 0,
    total_maintenance_items: 0,
    total_documents: 0,
    total_notes: 0,
    total_photos: 0,
    latest_service_date: null,
    latest_fuel_date: null,
    latest_odometer_km: null,
    latest_odometer_date: null,
    upcoming_maintenance_count: 0,
    due_soon_maintenance_count: 0,
    overdue_maintenance_count: 0,
    average_l_per_100km: null,
    recent_l_per_100km: null,
    towing_l_per_100km: null,
    tow_vehicle: null,
    propane_l_per_month: null,
    recent_propane_l_per_month: null,
    archived_at: null,
    archived_visible: true,
    is_shared_with_me: false,
    shared_by_username: null,
    share_permission: null,
    owner_relationship: null,
    owner_relationship_custom: null,
    ...overrides,
  }
}

/**
 * Build a vehicle-detail hero / key-facts payload: a distance-tracked vehicle
 * with no readings and nothing due.
 *
 * @param overrides Fields to replace on the default payload.
 * @returns A complete `VehicleDetailStats`.
 */
export function makeDetailStats(overrides: Partial<VehicleDetailStats> = {}): VehicleDetailStats {
  return {
    overdue_count: 0,
    upcoming_count: 0,
    due_soon_count: 0,
    usage_unit: 'distance',
    current_hours: null,
    latest_hours: null,
    average_l_per_hr: null,
    average_cost_per_hr: null,
    secondary_usage_enabled: false,
    latest_odometer_km: null,
    latest_odometer_date: null,
    last_service_date: null,
    last_fillup_date: null,
    spent_this_year: '0.00',
    year: 2026,
    ...overrides,
  }
}
