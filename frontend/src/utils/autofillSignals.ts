/** Whether a real person produced this event, not a script or an extension. */
export function isUserGesture(event: Event): boolean {
  return event.isTrusted
}

/** Whether the browser marks this field as autofilled; false where the selector is unknown. */
export function matchesAutofill(input: HTMLInputElement): boolean {
  for (const selector of [':autofill', ':-webkit-autofill']) {
    try {
      if (input.matches(selector)) return true
    } catch {
      // An engine that doesn't know the selector throws; try the next one.
    }
  }
  return false
}
