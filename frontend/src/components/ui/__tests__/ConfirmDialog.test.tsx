import { useEffect, type ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useNavigate, useParams, type NavigateFunction } from 'react-router-dom'
import { ConfirmProvider, useConfirm, type ConfirmOptions } from '../ConfirmDialog'
import { answerConfirm, withConfirm } from '../../../__tests__/confirmHelpers'

// Real en strings, so the default Cancel label reads "Cancel".
vi.mock('react-i18next', async () => (await import('@/__tests__/i18nEn')).reactI18nextEn())

let root: HTMLElement
beforeEach(() => {
  root = document.createElement('div')
  root.id = 'root'
  document.body.appendChild(root)
})
afterEach(() => {
  root.remove()
})

const DELETE: ConfirmOptions = { message: 'Delete this fuel record?', confirmLabel: 'Delete' }

/** A promise plus what it settled to, so a test can check it never settled too. */
interface Outcome {
  settled: boolean
  value: boolean | undefined
}

function track(promise: Promise<boolean>): Outcome {
  const outcome: Outcome = { settled: false, value: undefined }
  void promise.then((value) => {
    outcome.settled = true
    outcome.value = value
  })
  return outcome
}

// Lets the promise callbacks run.
async function flush(): Promise<void> {
  await act(async () => {
    await Promise.resolve()
  })
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>

/** Hands its confirm out through a callback so the test can drive it. */
function Caller({ onConfirm }: { onConfirm: (confirm: Confirm) => void }): null {
  const confirm = useConfirm()
  onConfirm(confirm)
  return null
}

describe('ConfirmDialog', () => {
  it('resolves true on confirm and false on cancel, Esc and backdrop', async () => {
    let confirm: Confirm = () => Promise.resolve(false)
    render(
      <ConfirmProvider>
        <Caller onConfirm={(c) => (confirm = c)} />
      </ConfirmProvider>,
      { container: root },
    )

    const answers: Array<[string, () => void, boolean]> = [
      ['confirm', () => fireEvent.click(screen.getByRole('button', { name: 'Delete' })), true],
      ['cancel', () => fireEvent.click(screen.getByRole('button', { name: 'Cancel' })), false],
      ['escape', () => fireEvent.keyDown(document.activeElement ?? document.body, { key: 'Escape' }), false],
      [
        'backdrop',
        () => {
          // A real click presses and lets go first; Dialog only dismisses when both ends are on the backdrop.
          const backdrop = screen.getByTestId('dialog-backdrop')
          fireEvent.pointerDown(backdrop)
          fireEvent.pointerUp(backdrop)
          fireEvent.click(backdrop)
        },
        false,
      ],
    ]
    for (const [how, answer, expected] of answers) {
      let outcome!: Outcome
      act(() => {
        outcome = track(confirm(DELETE))
      })
      expect(screen.getByRole('alertdialog'), how).toBeInTheDocument()
      answer()
      await flush()
      expect(outcome, how).toEqual({ settled: true, value: expected })
      expect(screen.queryByRole('alertdialog'), how).not.toBeInTheDocument()
    }
  })

  it('names the alertdialog by the message, focuses Cancel first', () => {
    let confirm: Confirm = () => Promise.resolve(false)
    render(
      <ConfirmProvider>
        <Caller onConfirm={(c) => (confirm = c)} />
      </ConfirmProvider>,
      { container: root },
    )
    // The link would take focus if Cancel weren't asked for by name.
    act(() => {
      void confirm({
        ...DELETE,
        detail: (
          <>
            This can't be undone. <a href="#">Details</a>
          </>
        ),
      })
    })
    const dialog = screen.getByRole('alertdialog', { name: 'Delete this fuel record?' })
    expect(dialog).toHaveAccessibleDescription("This can't be undone. Details")
    expect(root.contains(dialog)).toBe(false)
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Cancel' }))
    // Danger is the default tone.
    expect(screen.getByRole('button', { name: 'Delete' })).toHaveClass('text-danger')
  })

  it('breaks a long unbroken name instead of scrolling sideways', () => {
    let confirm: Confirm = () => Promise.resolve(false)
    render(
      <ConfirmProvider>
        <Caller onConfirm={(c) => (confirm = c)} />
      </ConfirmProvider>,
      { container: root },
    )
    const long = 'x'.repeat(120)
    act(() => {
      void confirm({ message: `Delete ${long}?`, detail: long, confirmLabel: 'Delete' })
    })
    expect(screen.getByText(`Delete ${long}?`)).toHaveClass('wrap-anywhere')
    expect(screen.getByText(long)).toHaveClass('wrap-anywhere')
  })

  it('tone default uses the primary button and cancelLabel overrides Cancel', () => {
    let confirm: Confirm = () => Promise.resolve(false)
    render(
      <ConfirmProvider>
        <Caller onConfirm={(c) => (confirm = c)} />
      </ConfirmProvider>,
      { container: root },
    )
    act(() => {
      void confirm({ message: 'Save this place?', confirmLabel: 'Save', cancelLabel: 'Skip', tone: 'default' })
    })
    expect(screen.getByRole('button', { name: 'Save' })).not.toHaveClass('text-danger')
    expect(screen.getByRole('button', { name: 'Save' })).toHaveClass('bg-(--accent-solid)')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Skip' }))
  })

  it('a second confirm resolves the first false', async () => {
    let confirm: Confirm = () => Promise.resolve(false)
    render(
      <ConfirmProvider>
        <Caller onConfirm={(c) => (confirm = c)} />
      </ConfirmProvider>,
      { container: root },
    )
    let first!: Outcome
    let second!: Outcome
    act(() => {
      first = track(confirm(DELETE))
    })
    act(() => {
      second = track(confirm({ message: 'Remove this vehicle?', confirmLabel: 'Remove' }))
    })
    await flush()
    expect(first).toEqual({ settled: true, value: false })
    expect(second.settled).toBe(false)
    expect(screen.getAllByRole('alertdialog')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await flush()
    expect(second).toEqual({ settled: true, value: true })
  })

  // The caller's own cleanup does this: a pending confirm's owner always sits
  // inside the provider, so it unmounts with it.
  it('unmounting the provider resolves a pending confirm false', async () => {
    let confirm: Confirm = () => Promise.resolve(false)
    const { unmount } = render(
      <ConfirmProvider>
        <Caller onConfirm={(c) => (confirm = c)} />
      </ConfirmProvider>,
      { container: root },
    )
    let outcome!: Outcome
    act(() => {
      outcome = track(confirm(DELETE))
    })
    unmount()
    await flush()
    expect(outcome).toEqual({ settled: true, value: false })
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('the caller unmounting closes its confirm and resolves false', async () => {
    let confirm: Confirm = () => Promise.resolve(false)
    function Shell({ shown }: { shown: boolean }): ReactElement {
      return <ConfirmProvider>{shown ? <Caller onConfirm={(c) => (confirm = c)} /> : null}</ConfirmProvider>
    }
    const { rerender } = render(<Shell shown />, { container: root })
    let outcome!: Outcome
    act(() => {
      outcome = track(confirm(DELETE))
    })
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    rerender(<Shell shown={false} />)
    await flush()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(outcome).toEqual({ settled: true, value: false })
  })

  it('a stale caller unmounting leaves a newer confirm alone', async () => {
    let confirmA: Confirm = () => Promise.resolve(false)
    let confirmB: Confirm = () => Promise.resolve(false)
    function Shell({ showA }: { showA: boolean }): ReactElement {
      return (
        <ConfirmProvider>
          {showA ? <Caller onConfirm={(c) => (confirmA = c)} /> : null}
          <Caller onConfirm={(c) => (confirmB = c)} />
        </ConfirmProvider>
      )
    }
    const { rerender } = render(<Shell showA />, { container: root })
    let a!: Outcome
    let b!: Outcome
    act(() => {
      a = track(confirmA(DELETE))
    })
    act(() => {
      b = track(confirmB({ message: 'Remove this vehicle?', confirmLabel: 'Remove' }))
    })
    await flush()
    expect(a).toEqual({ settled: true, value: false })

    rerender(<Shell showA={false} />)
    await flush()
    expect(screen.getByRole('alertdialog', { name: 'Remove this vehicle?' })).toBeInTheDocument()
    expect(b.settled).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await flush()
    expect(b).toEqual({ settled: true, value: true })
  })

  it('a route change closes a pending confirm', async () => {
    let confirm: Confirm = () => Promise.resolve(false)
    let navigate: NavigateFunction = () => {}
    // Sits outside any Route, so it stays mounted across the navigation.
    function Page({ onReady }: { onReady: (go: NavigateFunction, ask: Confirm) => void }): null {
      onReady(useNavigate(), useConfirm())
      return null
    }
    render(
      <MemoryRouter initialEntries={['/a']}>
        <ConfirmProvider>
          <Page
            onReady={(go, ask) => {
              navigate = go
              confirm = ask
            }}
          />
        </ConfirmProvider>
      </MemoryRouter>,
      { container: root },
    )
    let outcome!: Outcome
    act(() => {
      outcome = track(confirm(DELETE))
    })
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    await act(async () => {
      await navigate('/b')
    })
    await flush()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(outcome).toEqual({ settled: true, value: false })
  })

  it('a page that asks on every route opens its new confirm after the reset', async () => {
    let navigate: NavigateFunction = () => {}
    const outcomes: Record<string, Outcome> = {}
    // Same element for both vins, so it stays mounted and its effect re-runs.
    function VehiclePage(): null {
      const { vin = '' } = useParams()
      const confirm = useConfirm()
      useEffect(() => {
        outcomes[vin] = track(confirm({ message: `Leave ${vin}?`, confirmLabel: 'Leave' }))
      }, [vin, confirm])
      return null
    }
    function Nav({ onReady }: { onReady: (go: NavigateFunction) => void }): null {
      onReady(useNavigate())
      return null
    }
    render(
      <MemoryRouter initialEntries={['/vehicles/A']}>
        <ConfirmProvider>
          <Nav onReady={(go) => (navigate = go)} />
          <Routes>
            <Route path="/vehicles/:vin" element={<VehiclePage />} />
          </Routes>
        </ConfirmProvider>
      </MemoryRouter>,
      { container: root },
    )
    expect(screen.getByRole('alertdialog', { name: 'Leave A?' })).toBeInTheDocument()
    await act(async () => {
      await navigate('/vehicles/B')
    })
    await flush()
    expect(outcomes.A).toEqual({ settled: true, value: false })
    expect(screen.getByRole('alertdialog', { name: 'Leave B?' })).toBeInTheDocument()
    expect(outcomes.B.settled).toBe(false)
  })

  it("a dead owner's confirm never opens", async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    let outcome: Outcome | null = null
    // Like SpotRentalForm: awaits a save, then prompts.
    function SaveThenAsk(): ReactElement {
      const confirm = useConfirm()
      const onSave = async (): Promise<void> => {
        await gate
        outcome = track(confirm({ message: 'Save this place?', confirmLabel: 'Save', tone: 'default' }))
      }
      return <button onClick={() => void onSave()}>Save rental</button>
    }
    function Shell({ shown }: { shown: boolean }): ReactElement {
      return <ConfirmProvider>{shown ? <SaveThenAsk /> : null}</ConfirmProvider>
    }
    const { rerender } = render(<Shell shown />, { container: root })
    fireEvent.click(screen.getByRole('button', { name: 'Save rental' }))
    rerender(<Shell shown={false} />)
    await act(async () => {
      release()
      await gate
    })
    await flush()
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(outcome).toEqual({ settled: true, value: false })
  })

  it('a live caller under StrictMode still opens its confirm', async () => {
    let release: () => void = () => {}
    const gate = new Promise<void>((resolve) => {
      release = resolve
    })
    function SaveThenAsk(): ReactElement {
      const confirm = useConfirm()
      const onSave = async (): Promise<void> => {
        await gate
        void confirm({ message: 'Save this place?', confirmLabel: 'Save', tone: 'default' })
      }
      return <button onClick={() => void onSave()}>Save rental</button>
    }
    render(
      <ConfirmProvider>
        <SaveThenAsk />
      </ConfirmProvider>,
      { container: root, reactStrictMode: true },
    )
    fireEvent.click(screen.getByRole('button', { name: 'Save rental' }))
    await act(async () => {
      release()
      await gate
    })
    expect(screen.getByRole('alertdialog', { name: 'Save this place?' })).toBeInTheDocument()
  })

  it('the returned confirm is stable across provider re-renders', async () => {
    const seen = new Set<Confirm>()
    let confirm: Confirm = () => Promise.resolve(false)
    function Shell({ label }: { label: string }): ReactElement {
      return (
        <ConfirmProvider>
          <p>{label}</p>
          <Caller
            onConfirm={(c) => {
              seen.add(c)
              confirm = c
            }}
          />
        </ConfirmProvider>
      )
    }
    const { rerender } = render(<Shell label="one" />, { container: root, reactStrictMode: true })
    let outcome!: Outcome
    act(() => {
      outcome = track(confirm(DELETE))
    })
    rerender(<Shell label="two" />)
    await flush()
    expect(seen.size).toBe(1)
    // And the open confirm survived it: no caller cleanup cancelled it.
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(outcome.settled).toBe(false)
  })

  it('throws outside a provider', () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => render(<Caller onConfirm={() => {}} />, { container: root })).toThrow(
      'useConfirm needs a ConfirmProvider',
    )
    error.mockRestore()
  })
})

describe('confirmHelpers', () => {
  function Asker({ onAnswer }: { onAnswer: (value: boolean) => void }): ReactElement {
    const confirm = useConfirm()
    return <button onClick={() => void confirm(DELETE).then(onAnswer)}>Delete record</button>
  }

  it('answerConfirm clicks the chosen button and waits for the dialog to go', async () => {
    const answers: boolean[] = []
    render(<Asker onAnswer={(v) => answers.push(v)} />, { container: root, wrapper: withConfirm })

    fireEvent.click(screen.getByRole('button', { name: 'Delete record' }))
    await answerConfirm('confirm', /fuel record/)
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete record' }))
    await answerConfirm('cancel')
    expect(answers).toEqual([true, false])
  })

  it('answerConfirm rejects on the wrong name', async () => {
    render(<Asker onAnswer={() => {}} />, { container: root, wrapper: withConfirm })
    fireEvent.click(screen.getByRole('button', { name: 'Delete record' }))
    await expect(answerConfirm('confirm', 'Remove this vehicle?')).rejects.toThrow()
  })

  it('answerConfirm rejects when the confirm has more than one other button', async () => {
    function ExtraButton(): ReactElement {
      const confirm = useConfirm()
      const ask = (): void => {
        void confirm({ ...DELETE, detail: <button>Undo</button> })
      }
      return <button onClick={ask}>Delete record</button>
    }
    render(<ExtraButton />, { container: root, wrapper: withConfirm })
    fireEvent.click(screen.getByRole('button', { name: 'Delete record' }))
    await expect(answerConfirm('confirm')).rejects.toThrow('no single confirm button')
  })

  it('answerConfirm rejects when the confirm has more than one Cancel', async () => {
    function ExtraCancel(): ReactElement {
      const confirm = useConfirm()
      const ask = (): void => {
        void confirm({ ...DELETE, detail: <button data-dialog-cancel>Never mind</button> })
      }
      return <button onClick={ask}>Delete record</button>
    }
    render(<ExtraCancel />, { container: root, wrapper: withConfirm })
    fireEvent.click(screen.getByRole('button', { name: 'Delete record' }))
    await expect(answerConfirm('cancel')).rejects.toThrow('no single Cancel')
  })

  it('answerConfirm rejects when no confirm is open', async () => {
    render(<Asker onAnswer={() => {}} />, { container: root, wrapper: withConfirm })
    await expect(answerConfirm('confirm')).rejects.toThrow()
  })
})
