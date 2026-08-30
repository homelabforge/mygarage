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
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_login: null,
    language: 'en',
    currency_code: 'USD',
    time_format: '12h',
    mobile_quick_entry_enabled: true,
    show_both_units: false,
    show_on_family_dashboard: false,
    family_dashboard_order: 0,
    unit_preference: 'imperial',
    resolved_units: IMPERIAL_UNITS,
    ...overrides,
  }
}
