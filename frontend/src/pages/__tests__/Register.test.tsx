import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { render } from '../../__tests__/test-utils'

// Bypass AuthProvider by mocking the hook directly, same pattern as Login.test.tsx.
const registerMock = vi.fn()
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    register: registerMock,
    user: null,
  }),
}))

// What /auth/users/count answers. Most tests don't care, so somebody's
// already registered unless a test says otherwise.
const usersCount = vi.hoisted(() => ({ hasUsers: true }))

// Mock axios so the api module (imported directly by Register for the
// /auth/users/count first-user check) doesn't error out on import.
vi.mock('axios', () => {
  interface MockAxios {
    post: ReturnType<typeof vi.fn>
    get: ReturnType<typeof vi.fn>
    interceptors: {
      request: { use: ReturnType<typeof vi.fn>; eject: ReturnType<typeof vi.fn> }
      response: { use: ReturnType<typeof vi.fn>; eject: ReturnType<typeof vi.fn> }
    }
    create: ReturnType<typeof vi.fn>
  }
  const mockAxios: MockAxios = {
    post: vi.fn(() => Promise.resolve({ data: {} })),
    get: vi.fn(() => Promise.resolve({ data: { has_users: usersCount.hasUsers } })),
    interceptors: {
      request: { use: vi.fn(), eject: vi.fn() },
      response: { use: vi.fn(), eject: vi.fn() },
    },
    create: vi.fn(),
  }
  mockAxios.create = vi.fn(() => mockAxios)
  return { default: mockAxios }
})

import Register from '../Register'

beforeEach(() => {
  registerMock.mockClear()
  usersCount.hasUsers = true
})

afterEach(() => {
  cleanup()
})

async function fillValidForm(user: ReturnType<typeof userEvent.setup>): Promise<void> {
  // Values chosen to pass client-side zod validation (makeRegisterSchema) so
  // handleSubmit actually calls onSubmit and reaches registerMock — the
  // 422 being tested is a server-side rule the client mirrors but a real
  // deployment could still reject (e.g. a rule added backend-only).
  await user.type(screen.getByLabelText('register.username'), 'newuser1')
  await user.type(screen.getByLabelText('register.email'), 'newuser1@example.com')
  await user.type(screen.getByLabelText('register.password'), 'Passw0rd!')
  await user.type(screen.getByLabelText('registerPage.confirmPasswordLabel'), 'Passw0rd!')
}

// [Final-review correction] This describe block does NOT fence the AuthContext
// bug found in Task 10c review — `vi.mock('../../contexts/AuthContext', ...)`
// at the top of this file replaces `register` with `registerMock`, so the REAL
// AuthContext.register (the code that used to collapse the AxiosError to
// `new Error(response.data.detail || ...)`, losing the array `detail` and
// dead-ending applyServerErrors' fieldErrors path) never runs here. Reverting
// that AuthContext fix would NOT fail these tests — `registerMock` rejects
// with an already-AxiosError-shaped object regardless of what the real
// AuthContext does. The actual fence for the AuthContext fix is
// `contexts/__tests__/AuthContext.test.tsx`'s "register propagates the
// original AxiosError (array detail intact) instead of collapsing it to a
// string Error" test, which exercises the real (unmocked) implementation.
//
// What THIS block genuinely fences is Register.tsx's OWN error-wiring —
// applyServerErrors attaching a field-addressed 422 problem to the right
// input, and getActionErrorMessage never stringifying an array `detail` as
// `[object Object]` — given an AxiosError-shaped rejection of the kind a
// (correctly) unmocked AuthContext would actually produce.
describe('Register — server-side 422 field-error wiring', () => {
  it('a weak-password 422 attaches its message to the password field, not a generic banner or [object Object]', async () => {
    registerMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [
            {
              type: 'value_error',
              loc: ['body', 'password'],
              msg: 'Password must contain at least one special character',
            },
          ],
        },
      },
    })

    const user = userEvent.setup()
    render(<Register />)

    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'register.submit' }))

    await waitFor(() => expect(registerMock).toHaveBeenCalledTimes(1))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Password must contain at least one special character')

    // The generic action-failure banner must NOT also appear — the problem
    // fully attached to a known field, so Register's `attached.length === 0
    // || unhandled.length > 0` guard should stay false.
    expect(screen.queryByText(/registerPage\.createAccountAction/)).not.toBeInTheDocument()

    // The actual bug: an array `detail` reaching String()/template coercion
    // anywhere in the pipeline.
    expect(document.body.textContent).not.toContain('[object Object]')
  })

  it('confirms the field-error path is reachable at all — fails if Register\'s own applyServerErrors wiring regresses', async () => {
    // Same rejection, but this test exists purely to prove the assertion above
    // isn't vacuously true. [Final-review correction: this does NOT exercise
    // AuthContext — see the describe-block comment above — `registerMock`
    // rejects directly, so AuthContext's own collapse-to-string-Error bug is
    // untestable from here regardless of pass/fail.] If Register.tsx's OWN
    // catch block stopped calling applyServerErrors correctly on this shape
    // (e.g. reverted to reading `err.message` instead of parsing
    // `fieldErrors`), no alert role would ever render and this findByRole
    // would time out and fail.
    registerMock.mockRejectedValueOnce({
      isAxiosError: true,
      message: 'Request failed with status code 422',
      response: {
        status: 422,
        data: {
          detail: [
            { type: 'value_error', loc: ['body', 'password'], msg: 'Too weak' },
          ],
        },
      },
    })

    const user = userEvent.setup()
    render(<Register />)

    await fillValidForm(user)
    await user.click(screen.getByRole('button', { name: 'register.submit' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Too weak')
  })
})

describe('Register: first-user check', () => {
  it('shows the admin badge when nobody has registered yet', async () => {
    usersCount.hasUsers = false
    render(<Register />)

    expect(await screen.findByText('registerPage.adminBadge')).toBeInTheDocument()
  })
})
