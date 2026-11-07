import { describe, expect, it } from 'vitest'
import { fuelStatusInterval } from '../useTelegramFuelStatus'

/** An axios-shaped failure; axios itself is mocked in the test setup. */
function failed(status?: number): unknown {
  return { isAxiosError: true, message: 'failed', response: status ? { status } : undefined }
}

describe('fuelStatusInterval (G5b-66)', () => {
  it.each([401, 403])('stops polling after a %i', (status) => {
    expect(fuelStatusInterval(failed(status))).toBe(false)
  })

  it.each([
    ['no error', null],
    ['a 500', failed(500)],
    ['a network error', failed()],
  ])('keeps polling with %s', (_case, error) => {
    expect(fuelStatusInterval(error)).toBe(15_000)
  })
})
