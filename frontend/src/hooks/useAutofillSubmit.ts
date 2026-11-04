import { useEffect, type RefObject } from 'react'
import { isUserGesture, matchesAutofill } from '../utils/autofillSignals'

// How long to wait after a fill before submitting. Safari fills the username
// and the password as two separate input events; this lets the second land.
const SETTLE_MS = 100

// Input types a person produces: typing, an IME, a paste, a drop, an undo.
// Deletions are caught by their `delete` prefix. A password manager's fill
// carries none of them (no inputType at all, or insertReplacementText).
const PERSON_INPUT_TYPES: ReadonlySet<string> = new Set([
  'insertText',
  'insertCompositionText',
  'insertFromPaste',
  'insertFromPasteAsQuotation',
  'insertFromDrop',
  'insertFromYank',
  'insertLineBreak',
  'insertParagraph',
  'historyUndo',
  'historyRedo',
])

/**
 * Submit a sign-in form as soon as a password manager fills it in, but only
 * when the person asked for that fill.
 *
 * Safari and the macOS / iOS Passwords app fill the username and password but
 * never press the button, so a saved login still needs a click, or a second
 * Enter. This presses it, once per visit to the page.
 *
 * Browsers also fill on their own: Firefox and Bitwarden on page load, Chrome
 * right after a logout. Submitting those would sign someone straight back in,
 * so a fill only counts once the person has clicked or pressed a key in one of
 * the two fields or on its label (a real event, not one a script or an
 * extension faked), and a task later, so a fill written during the click
 * itself doesn't count. A field the browser had already autofilled when the
 * person touched it is left alone too: Chrome marks its on-load fill that way
 * and only writes the value on the first click. Editing a field by hand clears
 * both marks.
 *
 * A sign-in still waiting on a fill is called off when the person edits a
 * field or submits the form themselves.
 *
 * A fill is a value that went from empty to more than one character in one
 * input or change event that wasn't typing, a paste, a drop or an undo, or one
 * that leaves the field matching `:autofill`. Change counts too because Safari
 * can fill without an input event.
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
    const doc = form.ownerDocument

    // Filled after the person asked for it.
    const requested = new WeakSet<HTMLInputElement>()
    // Already autofilled when the person touched a field, so never asked for.
    const stale = new WeakSet<HTMLInputElement>()
    const lastValue = new WeakMap<HTMLInputElement, string>()
    let armed = false
    let submitted = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let armTimer: ReturnType<typeof setTimeout> | undefined

    const field = (name: string): HTMLInputElement | null => {
      const el = form.elements.namedItem(name)
      return el instanceof HTMLInputElement ? el : null
    }
    const fields = (): HTMLInputElement[] =>
      [field(usernameField), field(passwordField)].filter((el): el is HTMLInputElement => el !== null)

    const submitIfFilled = (): void => {
      const username = field(usernameField)
      const password = field(passwordField)
      if (submitted || !username || !password || password.disabled) return
      if (username.value === '' || password.value === '') return
      if (!requested.has(password)) return
      submitted = true
      form.requestSubmit()
    }

    const onGesture = (event: Event): void => {
      if (!isUserGesture(event)) return
      // A click on a field's label focuses the field, so it counts as the field.
      const target = event.target instanceof HTMLLabelElement ? event.target.control : event.target
      if (!(target instanceof HTMLInputElement) || !fields().includes(target)) return
      for (const input of fields()) {
        if (matchesAutofill(input)) stale.add(input)
      }
      if (!armed && armTimer === undefined) {
        armTimer = setTimeout(() => {
          armed = true
        }, 0)
      }
    }

    const onFill = (event: Event): void => {
      const input = event.target
      if (!(input instanceof HTMLInputElement)) return
      if (input.name !== usernameField && input.name !== passwordField) return
      const before = lastValue.get(input) ?? ''
      lastValue.set(input, input.value)
      const inputType = event instanceof InputEvent ? event.inputType : ''
      if (inputType.startsWith('delete') || PERSON_INPUT_TYPES.has(inputType)) {
        // A person is editing: whatever was filled here is theirs now, and a
        // sign-in waiting on the fill would send a half-edited login.
        requested.delete(input)
        stale.delete(input)
        clearTimeout(timer)
        return
      }
      if (!armed || stale.has(input)) return
      if (!(before === '' && input.value.length > 1) && !matchesAutofill(input)) return
      requested.add(input)
      clearTimeout(timer)
      timer = setTimeout(submitIfFilled, SETTLE_MS)
    }

    // The person signed in themselves, so the pending one isn't needed.
    const onSubmit = (): void => clearTimeout(timer)

    doc.addEventListener('pointerdown', onGesture, true)
    doc.addEventListener('keydown', onGesture, true)
    form.addEventListener('input', onFill)
    form.addEventListener('change', onFill)
    form.addEventListener('submit', onSubmit)
    return () => {
      doc.removeEventListener('pointerdown', onGesture, true)
      doc.removeEventListener('keydown', onGesture, true)
      form.removeEventListener('input', onFill)
      form.removeEventListener('change', onFill)
      form.removeEventListener('submit', onSubmit)
      clearTimeout(timer)
      clearTimeout(armTimer)
    }
  }, [formRef, usernameField, passwordField])
}
