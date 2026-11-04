import { describe, expect, it } from 'vitest'
import { isUserGesture, matchesAutofill } from '../autofillSignals'

describe('autofillSignals', () => {
  // The Login tests stand this in, so this is the one place the real check runs.
  it("an event a script dispatched isn't a gesture", () => {
    const event = new PointerEvent('pointerdown', { bubbles: true })
    document.body.dispatchEvent(event)
    expect(isUserGesture(event)).toBe(false)
  })

  it("a plain input isn't autofilled, and the check doesn't throw", () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    expect(matchesAutofill(input)).toBe(false)
    input.remove()
  })
})
