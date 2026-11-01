/**
 * Helpers for the rejected-submit tests.
 *
 * `validationError` builds the axios-shaped 422 FastAPI sends, one problem per
 * field, so a test can aim a server error at a named control.
 * `registeredFieldNames` reads the names react-hook-form put on a rendered
 * form, which is what the knownFields guards compare against.
 * `submitAndSettle` and `whereA422Lands` let a guard wait for the save to
 * finish instead of guessing with a timer.
 */
import { fireEvent, waitFor, within } from '@testing-library/react'
import { expect, type Mock } from 'vitest'

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

/** The button that submits `form`: inside it, or in a footer pointing at it with `form=`. */
function submitButtonOf(form: HTMLFormElement): HTMLButtonElement {
  const button =
    form.querySelector<HTMLButtonElement>('button[type="submit"]') ??
    (form.id ? document.querySelector<HTMLButtonElement>(`button[type="submit"][form="${form.id}"]`) : null)
  if (!button) throw new Error(`no submit button for form #${form.id}`)
  return button
}

/**
 * Submit `form` and wait for the save to finish. The submit button is disabled
 * while react-hook-form is submitting and comes back once the catch has run, so
 * whatever the failure shows is on screen by then.
 */
export async function submitAndSettle(form: HTMLFormElement): Promise<void> {
  const button = submitButtonOf(form)
  fireEvent.submit(form)
  // If it never went disabled, waiting for it to be enabled proves nothing.
  expect(button).toBeDisabled()
  await waitFor(() => expect(button).toBeEnabled())
}

/** Where a field's server error ended up: with its field, only in the banner, or nowhere. */
export type Landing = 'field' | 'banner' | 'silent'

/**
 * Reject the next save with a 422 naming only `name`, submit, and say where
 * `msg` went. A 422 banner never repeats a field's message, so finding `msg` in
 * the form means it sits with its field. Keep `msg` unique per call, so an
 * older error can't answer for this one.
 */
export async function whereA422Lands(
  form: HTMLFormElement,
  save: Mock,
  name: string,
  msg: string,
  banner: () => HTMLElement | null
): Promise<Landing> {
  const calls = save.mock.calls.length
  save.mockRejectedValueOnce(validationError({ [name]: msg }))
  await submitAndSettle(form)
  // Client validation blocking the submit would read as silent otherwise.
  expect(save, `${name}: the save never ran`).toHaveBeenCalledTimes(calls + 1)
  if (within(form).queryByText(msg)) return 'field'
  return banner() ? 'banner' : 'silent'
}
