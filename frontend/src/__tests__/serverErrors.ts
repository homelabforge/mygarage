/**
 * Helpers for the rejected-submit tests.
 *
 * `validationError` builds the axios-shaped 422 FastAPI sends, one problem per
 * field, so a test can aim a server error at a named control.
 * `registeredFieldNames` reads the names react-hook-form put on a rendered
 * form, which is what the knownFields guards compare against.
 */

/** An axios-shaped 422 whose body names each field once, under `body`. */
export function validationError(problems: Record<string, string>): {
  isAxiosError: true
  message: string
  response: { status: 422; data: { detail: { type: string; loc: string[]; msg: string }[] } }
} {
  return {
    isAxiosError: true,
    message: 'Request failed with status code 422',
    response: {
      status: 422,
      data: {
        detail: Object.entries(problems).map(([field, msg]) => ({
          type: 'value_error',
          loc: ['body', field],
          msg,
        })),
      },
    },
  }
}

/**
 * Every `name` the form's controls carry, once each, minus the UI-only ones the
 * caller lists. register() writes the field path as `name`, so this is the set
 * a server error can be addressed to.
 */
export function registeredFieldNames(form: HTMLFormElement, uiOnly: readonly string[] = []): string[] {
  const names = Array.from(form.querySelectorAll<HTMLElement>('[name]'), (el) => el.getAttribute('name') ?? '')
  return [...new Set(names)].filter((name) => name !== '' && !uiOnly.includes(name)).sort()
}
