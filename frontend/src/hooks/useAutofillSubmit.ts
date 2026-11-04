import { useEffect, type RefObject } from 'react'

// How long to wait after a fill before submitting. Safari fills the username
// and the password as two separate input events; this lets the second land.
const SETTLE_MS = 100

// Input types a person produces: typing, an IME, a paste, a drop, a deletion.
// A password manager's fill carries none of them (no inputType at all, or
// insertReplacementText), and that's what tells a fill apart.
const PERSON_INPUT_TYPES: ReadonlySet<string> = new Set([
  'insertText',
  'insertCompositionText',
  'insertFromPaste',
  'insertFromPasteAsQuotation',
  'insertFromDrop',
  'insertFromYank',
  'insertLineBreak',
  'insertParagraph',
])

/** Whether the browser marks this field as autofilled; false where the selector is unknown. */
function matchesAutofill(input: HTMLInputElement): boolean {
  for (const selector of [':autofill', ':-webkit-autofill']) {
    try {
      if (input.matches(selector)) return true
    } catch {
      // An engine that doesn't know the selector throws; try the next one.
    }
  }
  return false
}

/**
 * Submit a sign-in form as soon as a password manager fills it in.
 *
 * Safari and the macOS / iOS Passwords app fill the username and password but
 * never press the button, so a saved login still needs a click, or a second
 * Enter (the first one only picks the login). This presses it, once per page
 * load, and only after a fill: typing or pasting still waits for Enter or the
 * button, and a failed sign-in is never retried on its own.
 *
 * Browsers don't announce a fill reliably, so it's recognised two ways: the
 * field matches `:autofill` (`:-webkit-autofill` in older Safari), or its
 * value went from empty to more than one character in a single input event
 * that wasn't typing, a paste or a drop.
 *
 * @param formRef The sign-in form. Its fields are found by name.
 * @param usernameField The `name` of the username input.
 * @param passwordField The `name` of the password input.
 */
export function useAutofillSubmit(
  formRef: RefObject<HTMLFormElement | null>,
  usernameField: string,
  passwordField: string,
): void {
  useEffect(() => {
    const form = formRef.current
    if (!form) return

    const filled = new WeakSet<HTMLInputElement>()
    const lastValue = new WeakMap<HTMLInputElement, string>()
    let submitted = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const field = (name: string): HTMLInputElement | null => {
      const el = form.elements.namedItem(name)
      return el instanceof HTMLInputElement ? el : null
    }

    const submitIfFilled = (): void => {
      const username = field(usernameField)
      const password = field(passwordField)
      if (submitted || !username || !password || password.disabled) return
      if (username.value === '' || password.value === '') return
      if (!filled.has(password) && !matchesAutofill(password)) return
      submitted = true
      form.requestSubmit()
    }

    const onInput = (event: Event): void => {
      const input = event.target
      if (!(input instanceof HTMLInputElement)) return
      const before = lastValue.get(input) ?? ''
      lastValue.set(input, input.value)
      const inputType = event instanceof InputEvent ? event.inputType : ''
      if (inputType.startsWith('delete') || PERSON_INPUT_TYPES.has(inputType)) {
        // A person is editing: anything filled earlier is theirs now.
        filled.delete(input)
        return
      }
      if (before === '' && input.value.length > 1) filled.add(input)
      clearTimeout(timer)
      timer = setTimeout(submitIfFilled, SETTLE_MS)
    }

    form.addEventListener('input', onInput)
    return () => {
      form.removeEventListener('input', onInput)
      clearTimeout(timer)
    }
  }, [formRef, usernameField, passwordField])
}
