import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { useForm, useFieldArray } from 'react-hook-form'
import { render } from '../../../__tests__/test-utils'
import { getActiveLocale, setActiveLocale } from '@/constants/i18n'
import { parseDecimalInput } from '@/utils/decimalInput'
import { INVALID_NUMBER } from '@/schemas/shared'
import NumberInput, { OVERWRITE_CHECK_MS, registerDecimal } from '../NumberInput'

// The global mock hands back bare keys. This one reads the shipped en strings so the
// hint tests can pin the actual words and the formatted value in them.
vi.mock('react-i18next', async () => {
  const en = (await import('@/locales/en/common.json')).default as Record<string, unknown>
  const lookup = (key: string): unknown =>
    key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en)
  const t = (key: string, opts?: Record<string, unknown>): string => {
    const text = lookup(key)
    if (typeof text !== 'string') return key
    return text.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name]))
  }
  const i18n = { language: 'en', changeLanguage: () => Promise.resolve() }
  return {
    useTranslation: () => ({ t, i18n }),
    initReactI18next: { type: '3rdParty', init: () => {} },
  }
})

interface Values { amount: number | typeof INVALID_NUMBER | undefined }
const onSubmit = vi.fn()

// `toHaveBeenCalledWith` matches ANY call in the mock's history, not just the
// most recent one. Without this, a later test's assertion can be satisfied by
// an earlier test's leftover call — see task-5-report.md addendum for the
// concrete case this masked.
beforeEach(() => onSubmit.mockClear())

function Harness(): React.JSX.Element {
  const { register, handleSubmit } = useForm<Values>()
  return (
    <form onSubmit={handleSubmit(v => onSubmit(v))}>
      <label htmlFor="amount">Amount</label>
      <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
      <button type="submit">Save</button>
    </form>
  )
}

describe('NumberInput', () => {
  it('renders a textbox, not a spinbutton, so locale separators survive', () => {
    render(<Harness />)
    expect(screen.getByRole('textbox', { name: 'Amount' })).toBeInTheDocument()
    expect(screen.getByLabelText('Amount')).toHaveAttribute('inputMode', 'decimal')
  })

  it('normalizes a comma decimal to a number', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), '528,25')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith({ amount: 528.25 })
  })

  it('submits undefined for an untouched field', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith({ amount: undefined })
  })

  it('emits the invalid sentinel rather than dropping bad text', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), 'abc')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith({ amount: INVALID_NUMBER })
  })

  it('follows the selected language for the ambiguous shape', async () => {
    setActiveLocale('pl')
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), '1,234')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenCalledWith({ amount: 1.234 })
    setActiveLocale('en')
  })

  it('passes a numeric default through untouched, without re-parsing it as locale text', async () => {
    // Regression fence: 1.234 under pl-PL is the ambiguous shape. Without the
    // `typeof raw === 'number'` guard in setValueAs, RHF's numeric defaultValue
    // is re-parsed as text and submits as 1234 — a 1000x corruption.
    setActiveLocale('pl')
    try {
      const user = userEvent.setup()
      function EditHarness(): React.JSX.Element {
        const { register, handleSubmit } = useForm<Values>({ defaultValues: { amount: 1.234 } })
        return (
          <form onSubmit={handleSubmit(v => onSubmit(v))}>
            <label htmlFor="amount">Amount</label>
            <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
            <button type="submit">Save</button>
          </form>
        )
      }
      render(<EditHarness />)
      await user.click(screen.getByRole('button', { name: 'Save' }))
      expect(onSubmit).toHaveBeenCalledWith({ amount: 1.234 })
    } finally {
      setActiveLocale('en')
    }
  })

  it('renders the ambiguity hint when given one', () => {
    render(<NumberInput id="x" ambiguityHint="Reading as 1.234" />)
    expect(screen.getByText('Reading as 1.234')).toBeInTheDocument()
  })

  it('merges the ambiguity hint id into aria-describedby when a hint is present', () => {
    render(<NumberInput id="amount" ambiguityHint="Reading as 1.234" />)
    expect(screen.getByRole('textbox')).toHaveAttribute('aria-describedby', 'amount-ambiguity')
  })

  it('does not set aria-describedby when there is no hint', () => {
    render(<NumberInput id="amount" />)
    expect(screen.getByRole('textbox')).not.toHaveAttribute('aria-describedby')
  })
})

describe('NumberInput ambiguity hint (D4)', () => {
  afterEach(() => setActiveLocale('en'))

  /** The hint paragraph, found by the id the input points at, so "no hint" can't pass by finding nothing. */
  const hintOf = (input: HTMLElement): HTMLElement | null => {
    const ids = (input.getAttribute('aria-describedby') ?? '').split(' ').filter(Boolean)
    const hint = ids.map(id => document.getElementById(id)).find(el => el?.textContent?.startsWith('Read as'))
    return hint ?? null
  }

  it('en: "1,234" took the grouping reading, so it says so and wires aria-describedby to it', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '1,234')
    const hint = screen.getByText('Read as 1,234')
    expect(hint.id).not.toBe('')
    expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(hint.id)
    expect(hintOf(input)).toBe(hint)
  })

  it('en: "10.123" took the decimal reading, so nothing shows (guard)', async () => {
    // Guard: passes on main. Mutation: hint on every ambiguous shape (D4 option b).
    const user = userEvent.setup()
    render(<Harness />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '10.123')
    expect(input).toHaveValue('10.123')
    expect(screen.queryByText(/^Read as/)).toBeNull()
    expect(input).not.toHaveAttribute('aria-describedby')
  })

  it('en: "0.000" stays quiet too, since it is the decimal reading even though both readings are 0 (guard)', async () => {
    // Guard: passes on main. Mutation: compare the value to the digits instead of checking the separator.
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), '0.000')
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('en: "0,000" is the grouping reading but zero either way, so it stays quiet (guard)', async () => {
    // Guard: passes on main. Mutation: drop the zero check in groupingReading.
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), '0,000')
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('de: "1.234" took the grouping reading, shown with German grouping', async () => {
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<Harness />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '1.234')
    const hint = screen.getByText('Read as 1.234')
    expect(input.getAttribute('aria-describedby')?.split(' ')).toContain(hint.id)
  })

  it('de: "1,234" is the decimal reading there, so nothing shows (guard)', async () => {
    // Guard: passes on main. Mutation: hint on every ambiguous shape (D4 option b).
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), '1,234')
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('clearing the field removes the hint and leaves no empty hint element behind', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '1,234')
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
    await user.clear(input)
    expect(screen.queryByText(/^Read as/)).toBeNull()
    expect(document.querySelector('[id$="-ambiguity"]')).toBeNull()
    expect(input).not.toHaveAttribute('aria-describedby')
  })

  it('still submits the grouping reading through registerDecimal with the hint showing', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.type(screen.getByLabelText('Amount'), '1,234')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
    expect(onSubmit).toHaveBeenCalledWith({ amount: 1234 })
  })

  it('an edit-mode numeric default shows nothing until the user types (guard)', async () => {
    // Guard: passes on main, where nothing ever showed. Mutation: seed the text from the DOM value at mount.
    // de reads the box's "1.234" as grouping, so keying off the box instead of the typing would speak up.
    setActiveLocale('de')
    function EditHarness(): React.JSX.Element {
      const { register } = useForm<Values>({ defaultValues: { amount: 1.234 } })
      return (
        <>
          <label htmlFor="amount">Amount</label>
          <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
        </>
      )
    }
    render(<EditHarness />)
    const input = screen.getByLabelText('Amount')
    expect(input).toHaveValue('1.234')
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('merges with an aria-describedby the caller already passes', async () => {
    const user = userEvent.setup()
    function Described(): React.JSX.Element {
      const { register } = useForm<Values>()
      return (
        <>
          <label htmlFor="amount">Amount</label>
          <p id="amount-error">bad</p>
          <NumberInput id="amount" aria-describedby="amount-error" {...registerDecimal(register, 'amount')} />
        </>
      )
    }
    render(<Described />)
    const input = screen.getByLabelText('Amount')
    expect(input).toHaveAttribute('aria-describedby', 'amount-error')
    await user.type(input, '1,234')
    const hint = screen.getByText('Read as 1,234')
    expect(input).toHaveAttribute('aria-describedby', `amount-error ${hint.id}`)
  })

  it('gets a hint id even when the caller passes no id', async () => {
    const user = userEvent.setup()
    function NoId(): React.JSX.Element {
      const { register } = useForm<Values>()
      return <NumberInput aria-label="Amount" {...registerDecimal(register, 'amount')} />
    }
    render(<NoId />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '1,234')
    const hint = screen.getByText('Read as 1,234')
    expect(hint.id).not.toBe('')
    expect(input).toHaveAttribute('aria-describedby', hint.id)
  })

  it('a controlled caller gets the hint and still receives every change event', async () => {
    const user = userEvent.setup()
    const seen = vi.fn()
    function Controlled(): React.JSX.Element {
      const [text, setText] = useState('')
      return (
        <>
          <label htmlFor="ctl">Amount</label>
          <NumberInput
            id="ctl"
            value={text}
            onChange={e => {
              seen(e.target.value)
              setText(e.target.value)
            }}
          />
        </>
      )
    }
    render(<Controlled />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '1,234')
    expect(seen).toHaveBeenLastCalledWith('1,234')
    expect(seen).toHaveBeenCalledTimes(5)
    expect(input).toHaveValue('1,234')
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
  })

  it('a controlled caller whose value is rewritten drops the hint for the text it did not type', async () => {
    const user = userEvent.setup()
    function Rewritten(): React.JSX.Element {
      const [text, setText] = useState('')
      return (
        <>
          <label htmlFor="ctl">Amount</label>
          <NumberInput id="ctl" value={text} onChange={e => setText(e.target.value)} />
          <button type="button" onClick={() => setText('2,345')}>Fill</button>
        </>
      )
    }
    render(<Rewritten />)
    await user.type(screen.getByLabelText('Amount'), '1,234')
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Fill' }))
    expect(screen.getByLabelText('Amount')).toHaveValue('2,345')
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('a controlled prefill shows nothing until the user types (guard)', () => {
    // Guard: passes on main. Mutation: derive from any string `value`, typed or not.
    render(<NumberInput id="ctl" aria-label="Amount" value="1,234" onChange={() => {}} />)
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('an explicit ambiguityHint still wins over the computed one (guard)', async () => {
    // Guard: passes on main, where only the prop could show. Mutation: prefer the computed hint.
    const user = userEvent.setup()
    function Explicit(): React.JSX.Element {
      const { register } = useForm<Values>()
      return (
        <>
          <label htmlFor="amount">Amount</label>
          <NumberInput id="amount" ambiguityHint="Custom reading" {...registerDecimal(register, 'amount')} />
        </>
      )
    }
    render(<Explicit />)
    await user.type(screen.getByLabelText('Amount'), '1,234')
    expect(screen.getByText('Custom reading')).toBeInTheDocument()
    expect(screen.queryByText(/^Read as/)).toBeNull()
  })

  it('keeps RHF ref and onBlur wired: blur marks it touched, a failed submit focuses it (guard)', async () => {
    // Guard: passes on main. Mutation: drop `ref` or `onBlur` on the way to Input.
    const user = userEvent.setup()
    const touched = vi.fn()
    function Wired(): React.JSX.Element {
      const { register, handleSubmit, formState } = useForm<Values>()
      touched(!!formState.touchedFields.amount)
      return (
        <form onSubmit={handleSubmit(v => onSubmit(v))}>
          <label htmlFor="amount">Amount</label>
          <NumberInput id="amount" {...registerDecimal(register, 'amount', { required: 'needed' })} />
          <button type="submit">Save</button>
        </form>
      )
    }
    render(<Wired />)
    const input = screen.getByLabelText('Amount')
    await user.click(input)
    await user.tab()
    expect(touched).toHaveBeenLastCalledWith(true)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(input).toHaveFocus()
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

describe('NumberInput hint across a language switch (R1-M1)', () => {
  afterEach(() => setActiveLocale('en'))

  // In the app i18n.ts moves the active locale first, then useTranslation re-renders.
  // The mocked hook here never re-renders, so the switch buttons re-render the form instead.
  function LanguageButtons({ onSwitch }: { onSwitch: (lang: string) => void }): React.JSX.Element {
    return (
      <>
        <button type="button" onClick={() => { setActiveLocale('de'); onSwitch('de') }}>Deutsch</button>
        <button type="button" onClick={() => { setActiveLocale('en'); onSwitch('en') }}>English</button>
      </>
    )
  }

  function Switchable(): React.JSX.Element {
    const { register, handleSubmit } = useForm<Values>()
    const [, setLang] = useState('')
    return (
      <form onSubmit={handleSubmit(v => onSubmit(v))}>
        <label htmlFor="amount">Amount</label>
        <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
        <LanguageButtons onSwitch={setLang} />
        <button type="submit">Save</button>
      </form>
    )
  }

  it('en -> de: "1.234" was read as 1.234, so no grouping hint appears and 1.234 is saved', async () => {
    const user = userEvent.setup()
    render(<Switchable />)
    await user.type(screen.getByLabelText('Amount'), '1.234')
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Deutsch' }))
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1.234 })
  })

  it('de -> en: "1.234" was read as 1234, so the hint keeps saying so and 1234 is saved', async () => {
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<Switchable />)
    await user.type(screen.getByLabelText('Amount'), '1.234')
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'English' }))
    // Same number, now written the English way.
    expect(screen.getByText('Read as 1,234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1234 })
  })

  it('a blur after the switch re-reads the box in the new language, and the hint follows (guard)', async () => {
    // Guard: passes on main. Mutation: don't restamp the locale on blur.
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<Switchable />)
    const input = screen.getByLabelText('Amount')
    await user.type(input, '1.234')
    await user.click(screen.getByRole('button', { name: 'English' }))
    await user.click(input)
    await user.tab()
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1.234 })
  })

  it('a controlled caller parses at save in the new language, so its hint follows it (guard)', async () => {
    // Guard: passes on main. Mutation: read controlled text under the typing-time stamp too.
    const saved = vi.fn()
    function Controlled(): React.JSX.Element {
      const [text, setText] = useState('')
      const [, setLang] = useState('')
      return (
        <>
          <label htmlFor="ctl">Amount</label>
          <NumberInput id="ctl" value={text} onChange={e => setText(e.target.value)} />
          <LanguageButtons onSwitch={setLang} />
          <button type="button" onClick={() => saved(parseDecimalInput(text, getActiveLocale()))}>Save</button>
        </>
      )
    }
    const user = userEvent.setup()
    render(<Controlled />)
    await user.type(screen.getByLabelText('Amount'), '1.234')
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Deutsch' }))
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(saved).toHaveBeenLastCalledWith(expect.objectContaining({ kind: 'value', value: 1234 }))
  })
})

describe('NumberInput: a number the form wrote stays that number (seeded decimal)', () => {
  afterEach(() => setActiveLocale('en'))

  interface Seeded { amount?: number | typeof INVALID_NUMBER }

  /** An edit form seeded with `seed`, plus buttons that reset and setValue it the way forms do. */
  function SeededForm({ seed }: { seed?: number }): React.JSX.Element {
    const { register, handleSubmit, reset, setValue } = useForm<Seeded>({ defaultValues: { amount: seed } })
    return (
      <form onSubmit={handleSubmit(v => onSubmit(v))}>
        <label htmlFor="amount">Amount</label>
        <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
        <button type="button" onClick={() => reset({ amount: 2.345 })}>Reset</button>
        <button type="button" onClick={() => setValue('amount', 1.234)}>Fill</button>
        <button type="submit">Save</button>
      </form>
    )
  }

  /** Focus the box and tab out without typing, which is when RHF re-reads it. */
  async function passThrough(user: ReturnType<typeof userEvent.setup>): Promise<void> {
    await user.click(screen.getByLabelText('Amount'))
    await user.tab()
  }

  it('de: a seeded 1.799 survives a focus and blur, and saves 1.799 with no hint', async () => {
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<SeededForm seed={1.799} />)
    await passThrough(user)
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1.799 })
  })

  it('de: reset to 2.345, then a focus and blur, saves 2.345', async () => {
    // 2.5 would read the same either way in de, so the reset value has the ambiguous shape.
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<SeededForm />)
    await user.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByLabelText('Amount')).toHaveValue('2.345')
    await passThrough(user)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 2.345 })
  })

  it('de: setValue(1.234), then a focus and blur, saves 1.234', async () => {
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<SeededForm />)
    await user.click(screen.getByRole('button', { name: 'Fill' }))
    await passThrough(user)
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1.234 })
  })

  it('de: typing "1.234" over a seed is the user\'s text, so it saves 1234 and says so (guard)', async () => {
    // Guard: passes on main. Mutation: keep returning the seed for its text after the user changed the box.
    setActiveLocale('de')
    const user = userEvent.setup()
    render(<SeededForm seed={1.234} />)
    const input = screen.getByLabelText('Amount')
    await user.clear(input)
    await user.type(input, '1.234')
    await user.tab()
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1234 })
  })

  it('en: a seeded 1.799 still saves 1.799 after a focus and blur (guard)', async () => {
    // Guard: passes on main, where en reads the dot as a decimal anyway.
    const user = userEvent.setup()
    render(<SeededForm seed={1.799} />)
    await passThrough(user)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1.799 })
  })
})

describe('NumberInput: what the form wrote vs what the user typed, at the edges', () => {
  afterEach(() => setActiveLocale('en'))

  interface Edge { amount?: number | typeof INVALID_NUMBER }

  it('de: after setValue(undefined), pasting the old seed text is the user\'s text, read in German', async () => {
    setActiveLocale('de')
    function Cleared(): React.JSX.Element {
      const { register, handleSubmit, setValue } = useForm<Edge>({ defaultValues: { amount: 1.234 } })
      return (
        <form onSubmit={handleSubmit(v => onSubmit(v))}>
          <label htmlFor="amount">Amount</label>
          <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
          <button type="button" onClick={() => setValue('amount', undefined)}>Clear</button>
          <button type="submit">Save</button>
        </form>
      )
    }
    const user = userEvent.setup()
    render(<Cleared />)
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    const input = screen.getByLabelText('Amount')
    expect(input).toHaveValue('')
    await user.click(input)
    await user.paste('1.234')
    await user.tab()
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1234 })
  })

  it('de: a code write of the same text the user typed takes the hint down, and saves the written number', async () => {
    setActiveLocale('de')
    function Filled(): React.JSX.Element {
      const { register, handleSubmit, setValue } = useForm<Edge>()
      return (
        <form onSubmit={handleSubmit(v => onSubmit(v))}>
          <label htmlFor="amount">Amount</label>
          <NumberInput id="amount" {...registerDecimal(register, 'amount')} />
          <button type="button" onClick={() => setValue('amount', 1.234)}>Fill</button>
          <button type="submit">Save</button>
        </form>
      )
    }
    const user = userEvent.setup()
    render(<Filled />)
    await user.type(screen.getByLabelText('Amount'), '1.234')
    await user.tab()
    expect(screen.getByText('Read as 1.234')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Fill' }))
    // setValue fires no event here, so the hint goes on the next overwrite check.
    await waitFor(() => expect(screen.queryByText(/^Read as/)).toBeNull(), { timeout: OVERWRITE_CHECK_MS * 4 })
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ amount: 1.234 })
  })

  it('de: a field-array row that moves up keeps its own number through a blur', async () => {
    setActiveLocale('de')
    interface Rows { rows: { amt?: number }[] }
    function Rows(): React.JSX.Element {
      const { register, handleSubmit, control } = useForm<Rows>({ defaultValues: { rows: [{ amt: 1.234 }, { amt: 2.345 }] } })
      const { fields, remove } = useFieldArray({ control, name: 'rows' })
      return (
        <form onSubmit={handleSubmit(v => onSubmit(v))}>
          {fields.map((f, i) => (
            <div key={f.id}>
              <label htmlFor={`row-${i}`}>Row {i}</label>
              <NumberInput id={`row-${i}`} {...registerDecimal(register, `rows.${i}.amt`)} />
              <button type="button" onClick={() => remove(i)}>Remove {i}</button>
            </div>
          ))}
          <button type="submit">Save</button>
        </form>
      )
    }
    const user = userEvent.setup()
    render(<Rows />)
    await user.click(screen.getByRole('button', { name: 'Remove 0' }))
    const input = screen.getByLabelText('Row 0')
    expect(input).toHaveValue('2.345')
    await user.click(input)
    await user.tab()
    expect(screen.queryByText(/^Read as/)).toBeNull()
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).toHaveBeenLastCalledWith({ rows: [{ amt: 2.345 }] })
  })

  it('a field holding unreadable text can be hidden and shown again, and still refuses to save', async () => {
    const validate = vi.fn((v: unknown) => (v === INVALID_NUMBER ? 'unreadable' : true))
    function Toggled(): React.JSX.Element {
      const { register, handleSubmit } = useForm<Edge>()
      const [shown, setShown] = useState(true)
      return (
        <form onSubmit={handleSubmit(v => onSubmit(v))}>
          {shown ? (
            <>
              <label htmlFor="amount">Amount</label>
              <NumberInput id="amount" {...registerDecimal(register, 'amount', { validate })} />
            </>
          ) : null}
          <button type="button" onClick={() => setShown(s => !s)}>Toggle</button>
          <button type="submit">Save</button>
        </form>
      )
    }
    const user = userEvent.setup()
    render(<Toggled />)
    await user.type(screen.getByLabelText('Amount'), 'abc')
    await user.click(screen.getByRole('button', { name: 'Toggle' }))
    await user.click(screen.getByRole('button', { name: 'Toggle' }))
    // The box gets back what was typed, not a symbol (which threw) or a blank that would read as empty.
    expect(screen.getByLabelText('Amount')).toHaveValue('abc')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
