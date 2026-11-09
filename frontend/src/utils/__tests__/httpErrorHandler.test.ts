import { describe, it, expect } from 'vitest'
import { parseApiError, getActionErrorMessage, actionErrorMessage } from '@/utils/httpErrorHandler'

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

  it('says not found (never the axios status line) when a 404 has no data.detail at all', () => {
    // No string detail means `detail` stays undefined (never axios's own
    // "Request failed with status code 404", which is all a blob download's
    // error leaves). "Check your input" was false here: nothing the user typed
    // made the thing go missing, so it gets the not-found template instead.
    const message = getActionErrorMessage(axios404(), 'restore the backup')
    expect(message).toBe('Failed to restore the backup. The requested resource was not found.')
  })

  it('treats a 404 whose detail is a validation-problem array as detail-less, never stringified', () => {
    // Contrived (only a 422 sends an array detail here), but it proves an
    // array never leaks through as [object Object].
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
    expect(message).toBe('Failed to restore the backup. The requested resource was not found.')
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

describe('getActionErrorMessage without a detail', () => {
  const axiosStatus = (status: number, detail?: unknown): unknown => ({
    isAxiosError: true,
    message: `Request failed with status code ${status}`,
    response: { status, data: detail === undefined ? {} : { detail } },
  })

  it('gives a detail-less 401, 403 or 404 its status template, not "check your input"', () => {
    expect(getActionErrorMessage(axiosStatus(401), 'load the vehicles')).toBe(
      'Failed to load the vehicles. Session expired. Please log in again.'
    )
    expect(getActionErrorMessage(axiosStatus(403), 'load the vehicles')).toBe(
      'Failed to load the vehicles. You do not have permission to perform this action.'
    )
    expect(getActionErrorMessage(axiosStatus(404), 'load the vehicles')).toBe(
      'Failed to load the vehicles. The requested resource was not found.'
    )
  })

  it('keeps "check your input" for a detail-less 400 or 422', () => {
    expect(getActionErrorMessage(axiosStatus(400), 'save the record')).toBe(
      'Failed to save the record. Please check your input.'
    )
    expect(getActionErrorMessage(axiosStatus(422), 'save the record')).toBe(
      'Failed to save the record. Please check your input.'
    )
  })
})

describe('getActionErrorMessage on a 502, 503 or 504', () => {
  const axiosStatus = (status: number, detail?: unknown): unknown => ({
    isAxiosError: true,
    message: `Request failed with status code ${status}`,
    response: { status, data: detail === undefined ? {} : { detail } },
  })

  it("puts a 503's detail after the action, so the fix it names reaches the user", () => {
    const detail = 'Set MYGARAGE_SETTINGS_KEY to a valid key, then try again.'
    expect(getActionErrorMessage(axiosStatus(503, detail), 'create the backup')).toBe(
      `Failed to create the backup. ${detail}`
    )
    expect(getActionErrorMessage(axiosStatus(502, 'AutoRef is down'), 'look up the VIN')).toBe(
      'Failed to look up the VIN. AutoRef is down'
    )
  })

  it('keeps the retry line for a 503 without a detail', () => {
    expect(getActionErrorMessage(axiosStatus(503), 'create the backup')).toBe(
      'Failed to create the backup. Service temporarily unavailable. Please try again shortly.'
    )
  })

  it("never shows axios's own text for a network failure", () => {
    // A network error retries too, and its `detail` is axios's "Network Error".
    expect(
      getActionErrorMessage({ isAxiosError: true, message: 'Network Error' }, 'save the record')
    ).toBe('Failed to save the record. Network error. Please check your connection.')
  })
})

describe('an already-parsed error', () => {
  const err403 = {
    isAxiosError: true,
    message: 'Request failed with status code 403',
    response: { status: 403, data: { detail: 'Nope' } },
  }

  it('comes back from parseApiError as is', () => {
    const parsed = parseApiError(err403)
    expect(parseApiError(parsed)).toBe(parsed)
  })

  it('still shows its detail when handed to getActionErrorMessage', () => {
    expect(getActionErrorMessage(parseApiError(err403), 'x')).toBe('Nope')
  })

  it('reads the same through actionErrorMessage', () => {
    expect(actionErrorMessage(parseApiError(err403), 'x')).toBe('Nope')
    expect(
      actionErrorMessage(
        parseApiError({ ...err403, response: { status: 500, data: {} } }),
        'save the record'
      )
    ).toBe('Failed to save the record. An unexpected server error occurred.')
  })

  it('is not mistaken for a plain object that only looks like one', () => {
    // JSON drops the stamp, so the copy is parsed like any unknown value.
    const lookalike: unknown = JSON.parse(JSON.stringify(parseApiError(err403)))
    expect(parseApiError(lookalike).message).toBe('An unexpected error occurred.')
  })
})
