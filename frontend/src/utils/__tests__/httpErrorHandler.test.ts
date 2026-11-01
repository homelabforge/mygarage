import { describe, it, expect } from 'vitest'
import { parseApiError, getActionErrorMessage } from '@/utils/httpErrorHandler'

const axios422 = (detail: unknown): unknown => ({
  isAxiosError: true,
  message: 'Request failed with status code 422',
  response: { status: 422, data: { detail } },
})

describe('parseApiError on a FastAPI 422', () => {
  it('extracts field problems instead of stringifying the array', () => {
    const parsed = parseApiError(axios422([
      { type: 'decimal_parsing', loc: ['body', 'deductible'], msg: 'Input should be a valid decimal', input: '' },
    ]))
    expect(parsed.status).toBe(422)
    expect(parsed.fieldErrors).toEqual([
      { field: 'deductible', message: 'Input should be a valid decimal', type: 'decimal_parsing' },
    ])
    expect(parsed.detail ?? '').not.toContain('[object Object]')
  })

  it('leaves a plain string detail alone and reports no field errors', () => {
    const parsed = parseApiError({
      isAxiosError: true,
      message: 'Request failed with status code 404',
      response: { status: 404, data: { detail: 'Vehicle not found' } },
    })
    expect(parsed.detail).toBe('Vehicle not found')
    expect(parsed.fieldErrors).toEqual([])
  })

  it('reports no field errors for a network failure', () => {
    const parsed = parseApiError({ isAxiosError: true, message: 'Network Error' })
    expect(parsed.isNetworkError).toBe(true)
    expect(parsed.fieldErrors).toEqual([])
  })
})

describe('getActionErrorMessage on a 500', () => {
  it('fills the action and the status message into the template', () => {
    // setup.ts inits the real i18next singleton, so this is what a user reads.
    // Without it tSafe hands back the raw "{{action}}" template.
    const axios500 = {
      isAxiosError: true,
      message: 'Request failed with status code 500',
      response: { status: 500, data: {} },
    }
    expect(getActionErrorMessage(axios500, 'save the record')).toBe(
      'Failed to save the record. An unexpected server error occurred.'
    )
  })
})

// Regression fence for Task 10c review IMPORTANT finding: getActionErrorMessage
// only surfaced `detail` for 400/422/409, so a 404 raised as
// `HTTPException(404, "X not found")` fell through to the generic "requested
// resource was not found" template — discarding backend specificity at every
// converted 10c site that surfaces a 404 (VehicleSharingModal x3,
// VehicleTransferWizard, DeleteUserModal, FamilyManagementModal,
// VehicleRemoveModal, SettingsBackupTab).
// What MyGarage's own handler sends (backend/app/utils/error_handlers.py,
// SecureErrorResponse.validation_error): the list is under `details`, not
// FastAPI's default `detail`, and each loc entry is stringified.
const myGarage422 = {
  isAxiosError: true,
  message: 'Request failed with status code 422',
  response: {
    status: 422,
    data: {
      error: true,
      message: 'Validation error',
      details: [
        {
          type: 'string_too_long',
          loc: ['body', 'environmental_rating_ghg'],
          msg: 'String should have at most 10 characters',
          input: 'AAAAAAAAAAA',
        },
      ],
      request_id: 'req-1',
    },
  },
}

describe("parseApiError on MyGarage's own 422 envelope", () => {
  it('reads the field problems from `details`', () => {
    const parsed = parseApiError(myGarage422)
    expect(parsed.status).toBe(422)
    expect(parsed.fieldErrors).toEqual([
      {
        field: 'environmental_rating_ghg',
        message: 'String should have at most 10 characters',
        type: 'string_too_long',
      },
    ])
    // Still never a toast string: the list is field content only.
    expect(parsed.detail).toBeUndefined()
  })
})

describe('getActionErrorMessage on a 404', () => {
  const axios404 = (detail?: unknown): unknown => ({
    isAxiosError: true,
    message: 'Request failed with status code 404',
    response: { status: 404, data: detail === undefined ? {} : { detail } },
  })

  it('surfaces a 404 detail string verbatim instead of the generic "not found" template', () => {
    expect(getActionErrorMessage(axios404('Backup file not found'), 'restore the backup')).toBe(
      'Backup file not found'
    )
    expect(getActionErrorMessage(axios404('Share not found'), 'revoke the share')).toBe(
      'Share not found'
    )
  })

  it('falls back to the translated template (never the axios status line) when a 404 has no data.detail at all', () => {
    // parseApiError leaves `detail` undefined both when the raw detail is a
    // 422-shaped validation array AND when there is no string detail at all
    // (C1 fix — the old code fell back to the AxiosError's own `.message`,
    // i.e. "Request failed with status code 404", the exact opaque string
    // this release exists to remove. That fallback was reachable on all 11
    // `responseType: 'blob'` download sites, where axios leaves the error
    // body an unreadable Blob, so `.detail` can never resolve there
    // regardless of what the backend raised). getActionErrorMessage now
    // falls through to the translated `actionFailedCheckInput` template,
    // with the action filled in by the en singleton from setup.ts.
    const message = getActionErrorMessage(axios404(), 'restore the backup')
    expect(message).toBe('Failed to restore the backup. Please check your input.')
  })

  it('surfaces a 404 detail that is a validation-problem array as the generic phrasing, never stringified', () => {
    // Contrived (FastAPI only sends array `detail` on 422 in this backend),
    // but exercises the branch where `parsed.detail` is genuinely undefined
    // at 404 status, proving the "check your input" fallback is reachable
    // and that an array never leaks through as [object Object].
    const message = getActionErrorMessage(
      {
        isAxiosError: true,
        message: 'Request failed with status code 404',
        response: {
          status: 404,
          data: { detail: [{ type: 'value_error', loc: ['body', 'vin'], msg: 'bad vin' }] },
        },
      },
      'restore the backup'
    )
    expect(message).not.toContain('[object Object]')
    expect(message).toBe('Failed to restore the backup. Please check your input.')
  })
})

// Regression fence for the final-review C2 CRITICAL: 401/403 were absent from
// the detail-surfacing branch, so login with a wrong password said "Failed to
// sign in. Session expired. Please log in again." instead of the backend's
// actual "Incorrect username or password" — a false statement on the app's
// front door. Same class as C1: only correct once the `error.message`
// fallback (C1) no longer masks a detail-less 401/403 with an axios status
// line.
describe('getActionErrorMessage on 401 and 403', () => {
  const axiosStatus = (status: number, detail?: unknown): unknown => ({
    isAxiosError: true,
    message: `Request failed with status code ${status}`,
    response: { status, data: detail === undefined ? {} : { detail } },
  })

  it('surfaces a 401 detail verbatim instead of the "session expired" template', () => {
    expect(getActionErrorMessage(axiosStatus(401, 'Incorrect username or password'), 'sign in')).toBe(
      'Incorrect username or password'
    )
  })

  it('surfaces a 403 detail verbatim instead of the generic "permission" template', () => {
    expect(getActionErrorMessage(axiosStatus(403, 'User account is inactive'), 'sign in')).toBe(
      'User account is inactive'
    )
    expect(
      getActionErrorMessage(
        axiosStatus(403, 'Registration is disabled. Please contact an administrator to create an account.'),
        'register'
      )
    ).toBe('Registration is disabled. Please contact an administrator to create an account.')
  })
})
