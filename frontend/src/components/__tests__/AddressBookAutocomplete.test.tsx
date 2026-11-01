import { useState } from 'react'
import type { ReactElement } from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AddressBookAutocomplete from '../AddressBookAutocomplete'
import type { AddressBookEntry } from '../../types/addressBook'

// Timers, fetches and state only, so jsdom covers all of it: nothing here
// depends on layout or stacking.

// vi.mock is hoisted above module-level consts, so the spy has to come from vi.hoisted.
const { get } = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../services/api', () => ({ default: { get } }))

const entry = (id: number, businessName: string): AddressBookEntry => ({
  id,
  business_name: businessName,
  source: 'manual',
  created_at: '2026-10-02T00:00:00Z',
  updated_at: '2026-10-02T00:00:00Z',
})

const SHELL = entry(1, 'Shell')
const SHEETZ = entry(2, 'Sheetz')
const ZZ_GARAGE = entry(3, 'Zz Garage')

type SearchResponse = { data: { entries: AddressBookEntry[] } }
const found = (...entries: AddressBookEntry[]): SearchResponse => ({ data: { entries } })

interface Deferred<T> {
  promise: Promise<T>
  resolve: (value: T) => void
  reject: (reason: unknown) => void
}

const deferred = <T,>(): Deferred<T> => {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

interface PickerProps {
  initial?: string
  onAddNew?: (typedName: string) => void
  withClear?: boolean
}

// The forms own the value, so the tests do too: a pick has to come back in as a new value.
function Picker({ initial = '', onAddNew, withClear = false }: PickerProps): ReactElement {
  const [value, setValue] = useState(initial)
  return (
    <AddressBookAutocomplete
      id="station"
      value={value}
      onChange={setValue}
      onClear={withClear ? () => setValue('') : undefined}
      onAddNew={onAddNew}
    />
  )
}

// Stands in for FuelRecordForm: + Add opens quick add, and saving it writes the new name into the box.
function PickerWithQuickAdd(): ReactElement {
  const [value, setValue] = useState('')
  const [adding, setAdding] = useState<string | null>(null)
  return (
    <>
      <AddressBookAutocomplete id="station" value={value} onChange={setValue} onAddNew={setAdding} />
      {adding !== null && (
        <button
          type="button"
          onClick={() => {
            setValue(`${adding} Garage`)
            setAdding(null)
          }}
        >
          save quick add
        </button>
      )}
    </>
  )
}

// Stands in for FuelRecordForm's receipt scan: it writes a station name nobody typed.
function PickerWithReceipt(): ReactElement {
  const [value, setValue] = useState('')
  return (
    <>
      <AddressBookAutocomplete id="station" value={value} onChange={setValue} />
      <button type="button" onClick={() => setValue('Speedway')}>
        scan receipt
      </button>
    </>
  )
}

// By id, not role: the G-3 cases below have to fail on their own assertion on the
// old picker, whose box was a plain textbox.
const input = (): HTMLInputElement => document.getElementById('station') as HTMLInputElement
const type = (text: string): void => {
  fireEvent.change(input(), { target: { value: text } })
}
const wait = async (ms: number): Promise<void> => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}
const option = (name: string): HTMLElement | null => screen.queryByRole('option', { name })
const pick = (name: string): void => {
  fireEvent.click(screen.getByRole('option', { name }))
}
const spinner = (container: HTMLElement): Element | null => container.querySelector('.animate-spin')
const clearButton = (): HTMLElement | null =>
  screen.queryByRole('button', { name: 'addressBookAutocomplete.clear' })

beforeEach(() => {
  vi.useFakeTimers()
  get.mockReset()
  get.mockResolvedValue(found(SHELL))
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('AddressBookAutocomplete after a pick (#194)', () => {
  it('a pick does not reopen the list', async () => {
    // The pick wrote the value, the value fired a search, and the list popped back ~300 ms later.
    render(<Picker />)
    type('Sh')
    await wait(300)
    pick('Shell')
    await wait(1000)
    expect(input().value).toBe('Shell')
    expect(get).toHaveBeenCalledTimes(1)
    expect(option('Shell')).not.toBeInTheDocument()
  })

  it('typing after a pick searches again', async () => {
    // Guard, passes before the fix: the fix mustn't swallow real typing. Killed by the mutant that
    // remembers the picked name and skips any search equal to it, never forgetting it.
    render(<Picker />)
    type('Sh')
    await wait(300)
    pick('Shell')
    type('Shel')
    type('Shell')
    await wait(300)
    expect(get).toHaveBeenCalledTimes(2)
    expect(get).toHaveBeenLastCalledWith(expect.stringContaining('search=Shell'))
    expect(option('Shell')).toBeInTheDocument()
  })

  it.each([
    { label: 'the pick changes the text', typed: ['Sh', 'She'] },
    { label: 'the picked name is already the text', typed: ['Shell', 'Shellx'] },
  ])('a search still in flight when you pick does not reopen the list ($label)', async ({ typed }) => {
    // The late answer used to land after the pick and open the list over it. Old matches hide
    // while a search is out (G-3), so the pick comes after typing back to the answered text.
    const late = deferred<SearchResponse>()
    render(<Picker />)
    type(typed[0])
    await wait(300)
    get.mockReturnValueOnce(late.promise)
    type(typed[1])
    await wait(300)
    expect(get).toHaveBeenCalledTimes(2)
    type(typed[0])
    pick('Shell')
    await act(async () => {
      late.resolve(found(SHEETZ))
    })
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(2)
    expect(option('Sheetz')).not.toBeInTheDocument()
    expect(option('Shell')).not.toBeInTheDocument()
    expect(screen.queryByText('addressBookAutocomplete.searching')).not.toBeInTheDocument()
    // Focus would show the late answer if it had landed in the entries.
    fireEvent.focus(input())
    expect(option('Sheetz')).not.toBeInTheDocument()
  })

  it('focusing the box again after a pick does not reopen the old matches', async () => {
    // The pick kept the matches for the text typed before it, and tapping back into
    // the box showed them under the picked name.
    get.mockResolvedValue(found(SHELL, SHEETZ))
    render(<Picker />)
    type('Sh')
    await wait(300)
    pick('Shell')
    fireEvent.blur(input())
    fireEvent.focus(input())
    await wait(1000)
    expect(input().value).toBe('Shell')
    expect(option('Shell')).not.toBeInTheDocument()
    expect(option('Sheetz')).not.toBeInTheDocument()
  })

  it('a pick made before the next search starts does not reopen the list', async () => {
    // The pick names what's already typed, so the value doesn't change and the waiting search
    // still fires afterwards. Checking the typed text only when the effect runs misses this.
    render(<Picker />)
    type('Shell')
    await wait(300)
    // Away and back inside the debounce: Shell's answer shows again with its search waiting.
    type('Shel')
    type('Shell')
    pick('Shell')
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(1)
    expect(option('Shell')).not.toBeInTheDocument()
  })

  it('a late failure after a close leaves the picker idle', async () => {
    // A dropped search skips its own finally, so closing has to stop the spinner itself. Old
    // matches hide while a search is out (G-3), so this closes with Escape, not a pick.
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {})
    const late = deferred<SearchResponse>()
    const { container } = render(<Picker withClear />)
    type('Sh')
    await wait(300)
    get.mockReturnValueOnce(late.promise)
    type('She')
    await wait(300)
    expect(spinner(container)).toBeInTheDocument()
    fireEvent.keyDown(input(), { key: 'Escape' })
    expect(spinner(container)).not.toBeInTheDocument()
    expect(clearButton()).toBeInTheDocument()
    await act(async () => {
      late.reject(new Error('network down'))
    })
    expect(spinner(container)).not.toBeInTheDocument()
    expect(clearButton()).toBeInTheDocument()
    expect(screen.queryByText('addressBookAutocomplete.searchFailed')).not.toBeInTheDocument()
    expect(errors).not.toHaveBeenCalled()
  })

  it('backspacing under two characters mid-search stops the spinner', async () => {
    // Under two characters drops the running search, so its spinner and its late answer go too.
    const late = deferred<SearchResponse>()
    const { container } = render(<Picker />)
    type('Sh')
    await wait(300)
    get.mockReturnValueOnce(late.promise)
    type('She')
    await wait(300)
    expect(spinner(container)).toBeInTheDocument()
    type('S')
    await wait(300)
    expect(spinner(container)).not.toBeInTheDocument()
    await act(async () => {
      late.resolve(found(SHEETZ))
    })
    expect(spinner(container)).not.toBeInTheDocument()
    expect(option('Sheetz')).not.toBeInTheDocument()
    expect(option('Shell')).not.toBeInTheDocument()
  })

  it('opening an edit form with a saved station does not open the list', async () => {
    // The seeded name used to be searched like typing, so the list opened by itself.
    render(<Picker initial="Shell X" />)
    await wait(1000)
    expect(get).not.toHaveBeenCalled()
    expect(option('Shell')).not.toBeInTheDocument()
  })

  it('a station returned by quick add does not reopen the list', async () => {
    // Nothing matches the typed text, so + Add shows; once added, the new name would match.
    get.mockResolvedValue(found(ZZ_GARAGE))
    get.mockResolvedValueOnce(found())
    render(<PickerWithQuickAdd />)
    type('Zz')
    await wait(300)
    fireEvent.click(screen.getByRole('option', { name: 'addressBookAutocomplete.addToAddressBook' }))
    fireEvent.click(screen.getByRole('button', { name: 'save quick add' }))
    expect(input().value).toBe('Zz Garage')
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(1)
    expect(option('Zz Garage')).not.toBeInTheDocument()
  })

  it('a parent write mid-search drops the search', async () => {
    // A receipt scan landing while a search was out let that answer open the list
    // for text no longer in the box. It lands inside the next debounce on purpose.
    const late = deferred<SearchResponse>()
    get.mockReturnValueOnce(late.promise)
    render(<PickerWithReceipt />)
    type('Sh')
    await wait(300)
    expect(get).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'scan receipt' }))
    expect(input().value).toBe('Speedway')
    await act(async () => {
      late.resolve(found(SHELL))
    })
    expect(option('Shell')).not.toBeInTheDocument()
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(1)
    expect(option('Shell')).not.toBeInTheDocument()
  })

  it('a new onAddNew each render does not refetch', async () => {
    // Callers pass an inline function, and a new one each render used to refire the search.
    const { rerender } = render(<Picker onAddNew={vi.fn()} />)
    type('Sh')
    await wait(300)
    expect(get).toHaveBeenCalledTimes(1)
    rerender(<Picker onAddNew={vi.fn()} />)
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('the clear button closes an open list', async () => {
    // Guard, passes before the fix: clearing empties the value from the parent, which nobody typed.
    // Killed by the mutant that runs the typed-only return before the short-value branch.
    render(<Picker withClear />)
    type('Sh')
    await wait(300)
    expect(option('Shell')).toBeInTheDocument()
    fireEvent.click(clearButton() as HTMLElement)
    await wait(300)
    expect(input().value).toBe('')
    expect(option('Shell')).not.toBeInTheDocument()
  })
})

describe('AddressBookAutocomplete after a close (#194)', () => {
  const closers = [
    { label: 'Escape', close: (): void => void fireEvent.keyDown(input(), { key: 'Escape' }) },
    { label: 'a click outside', close: (): void => void fireEvent.mouseDown(document.body) },
  ]

  it.each(closers)('closing the list drops the search still waiting ($label)', async ({ close }) => {
    // Closing only hid the list, so the search waiting out the debounce fired anyway and opened it again.
    render(<Picker />)
    type('Sh')
    await wait(300)
    type('She')
    // Open on "Searching" for the new text; the old matches hide until it answers (G-3).
    expect(screen.getByText('addressBookAutocomplete.searching')).toBeInTheDocument()
    close()
    expect(screen.queryByText('addressBookAutocomplete.searching')).not.toBeInTheDocument()
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(1)
    expect(option('Shell')).not.toBeInTheDocument()
  })

  it.each(closers)('closing the list drops the search already running ($label)', async ({ close }) => {
    // Closing only hid the list, so the running search kept its spinner and its late answer opened it again.
    const late = deferred<SearchResponse>()
    const { container } = render(<Picker />)
    type('Sh')
    await wait(300)
    get.mockReturnValueOnce(late.promise)
    type('She')
    await wait(300)
    expect(get).toHaveBeenCalledTimes(2)
    expect(spinner(container)).toBeInTheDocument()
    close()
    expect(option('Shell')).not.toBeInTheDocument()
    expect(spinner(container)).not.toBeInTheDocument()
    await act(async () => {
      late.resolve(found(SHEETZ))
    })
    await wait(1000)
    expect(get).toHaveBeenCalledTimes(2)
    expect(option('Shell')).not.toBeInTheDocument()
    expect(option('Sheetz')).not.toBeInTheDocument()
  })

  it('typing again after Escape opens the list', async () => {
    // Guard, passes before the fix: a close mustn't stop searching for good. Killed by the
    // mutant where Escape sets a closed flag the search checks and typing never clears.
    render(<Picker />)
    type('Sh')
    await wait(300)
    fireEvent.keyDown(input(), { key: 'Escape' })
    expect(option('Shell')).not.toBeInTheDocument()
    type('She')
    await wait(300)
    expect(get).toHaveBeenCalledTimes(2)
    expect(option('Shell')).toBeInTheDocument()
  })
})

describe('AddressBookAutocomplete as a combobox (G-4)', () => {
  it('ArrowDown moves aria-activedescendant through the options and Enter picks it', async () => {
    // The highlight was a CSS class only, so a screen reader never heard which row was active.
    get.mockResolvedValue(found(SHELL, SHEETZ))
    render(<Picker />)
    input().focus()
    type('Sh')
    await wait(300)
    const box = screen.getByRole('combobox')
    expect(box).toHaveAttribute('aria-expanded', 'true')
    expect(box).toHaveAttribute('aria-autocomplete', 'list')
    const list = screen.getByRole('listbox')
    expect(box).toHaveAttribute('aria-controls', list.id)
    const [shell, sheetz] = within(list).getAllByRole('option')
    expect(box).not.toHaveAttribute('aria-activedescendant')
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    expect(box).toHaveAttribute('aria-activedescendant', shell.id)
    expect(shell).toHaveAttribute('aria-selected', 'true')
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    expect(box).toHaveAttribute('aria-activedescendant', sheetz.id)
    expect(shell).toHaveAttribute('aria-selected', 'false')
    expect(sheetz).toHaveAttribute('aria-selected', 'true')
    // Focus never leaves the box, and the options stay out of the Tab order.
    expect(box).toHaveFocus()
    expect(sheetz).toHaveAttribute('tabindex', '-1')
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(input().value).toBe('Sheetz')
    expect(box).toHaveAttribute('aria-expanded', 'false')
  })

  it('+ Add is the last option, so the arrow keys reach it', async () => {
    // + Add was a separate button the arrow keys skipped, and Enter did nothing with no matches.
    get.mockResolvedValue(found())
    const onAddNew = vi.fn()
    render(<Picker onAddNew={onAddNew} />)
    type('Zz')
    await wait(300)
    fireEvent.keyDown(input(), { key: 'ArrowDown' })
    fireEvent.keyDown(input(), { key: 'Enter' })
    expect(onAddNew).toHaveBeenCalledWith('Zz')
  })

  it('Escape with the list open closes the list, not the drawer around it', async () => {
    // Escape reached the drawer's document listener and shut the whole form.
    const drawerEscape = vi.fn()
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') drawerEscape()
    }
    document.addEventListener('keydown', onKey)
    try {
      render(<Picker />)
      type('Sh')
      await wait(300)
      expect(screen.getByText('Shell')).toBeInTheDocument()
      fireEvent.keyDown(input(), { key: 'Escape' })
      expect(screen.queryByText('Shell')).not.toBeInTheDocument()
      expect(drawerEscape).not.toHaveBeenCalled()
      // With the list shut, Escape is the drawer's again.
      fireEvent.keyDown(input(), { key: 'Escape' })
      expect(drawerEscape).toHaveBeenCalledTimes(1)
    } finally {
      document.removeEventListener('keydown', onKey)
    }
  })

  it('a status line announces searching, then the count', async () => {
    // Nothing was announced, so a screen reader user typed into silence.
    const late = deferred<SearchResponse>()
    get.mockReturnValueOnce(late.promise)
    render(<Picker />)
    type('Sh')
    await wait(300)
    expect(screen.getByRole('status')).toHaveTextContent('combobox.searching')
    await act(async () => {
      late.resolve(found(SHELL, SHEETZ))
    })
    expect(screen.getByRole('status')).toHaveTextContent('combobox.results')
  })
})

describe('AddressBookAutocomplete empty state (G-3)', () => {
  const noMatches = (): HTMLElement | null => screen.queryByText('addressBookAutocomplete.noMatches')
  const searchingRow = (): HTMLElement | null => screen.queryByText('addressBookAutocomplete.searching')

  it('no "No matches" for text whose search has not answered yet', async () => {
    // The empty state belonged to the last search but read the current text, so "Shelz" got
    // a "No matches" before anyone searched it, then the panel vanished while it ran.
    get.mockResolvedValueOnce(found())
    render(<Picker onAddNew={vi.fn()} />)
    type('Shel')
    await wait(300)
    expect(noMatches()).toBeInTheDocument()
    const late = deferred<SearchResponse>()
    get.mockReturnValueOnce(late.promise)
    type('Shelz')
    expect(noMatches()).not.toBeInTheDocument()
    expect(searchingRow()).toBeInTheDocument()
    await wait(300)
    expect(get).toHaveBeenCalledTimes(2)
    expect(noMatches()).not.toBeInTheDocument()
    expect(searchingRow()).toBeInTheDocument()
    await act(async () => {
      late.resolve(found())
    })
    expect(noMatches()).toBeInTheDocument()
    expect(searchingRow()).not.toBeInTheDocument()
  })

  it('old matches hide while the next search is out', async () => {
    // The last search's hits stayed clickable through the debounce and the next request.
    const late = deferred<SearchResponse>()
    render(<Picker />)
    type('Sh')
    await wait(300)
    expect(screen.getByText('Shell')).toBeInTheDocument()
    get.mockReturnValueOnce(late.promise)
    type('Shx')
    expect(screen.queryByText('Shell')).not.toBeInTheDocument()
    expect(searchingRow()).toBeInTheDocument()
    await wait(300)
    expect(screen.queryByText('Shell')).not.toBeInTheDocument()
    await act(async () => {
      late.resolve(found(SHEETZ))
    })
    expect(screen.getByText('Sheetz')).toBeInTheDocument()
  })

  it('a failed search says so instead of "No matches"', async () => {
    // The catch emptied the matches and left the panel open, which read as "No matches".
    get.mockResolvedValueOnce(found())
    render(<Picker onAddNew={vi.fn()} />)
    type('Sh')
    await wait(300)
    expect(noMatches()).toBeInTheDocument()
    get.mockRejectedValueOnce(new Error('network down'))
    type('She')
    await wait(300)
    expect(noMatches()).not.toBeInTheDocument()
    expect(screen.getByText('addressBookAutocomplete.searchFailed')).toBeInTheDocument()
    expect(screen.queryByText('addressBookAutocomplete.addToAddressBook')).not.toBeInTheDocument()
  })
})

describe('Enter with the list open and nothing highlighted', () => {
  it('closes the list, and the next Enter submits the form around it', async () => {
    // Enter was swallowed while the list showed, so the fuel form couldn't be saved from the keyboard.
    // Real timers: user-event and Testing Library's async helpers wait on them.
    vi.useRealTimers()
    const user = userEvent.setup()
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <Picker />
        <button type="submit">save</button>
      </form>
    )
    input().focus()
    type('Sh')
    expect(await screen.findByRole('listbox')).toBeInTheDocument()

    await user.keyboard('{Enter}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(onSubmit).not.toHaveBeenCalled()

    await user.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledTimes(1)
    expect(input().value).toBe('Sh')
  })
})
