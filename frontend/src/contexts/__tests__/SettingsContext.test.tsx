/**
 * Settings tabs autosave: an edit triggers a debounced save. An edit whose
 * debounce fires while an earlier save (or its post-save refresh) is still
 * running has to be saved once that one finishes, not dropped.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useEffect, type ReactElement } from 'react'
import { render, screen, act, fireEvent } from '@testing-library/react'
import { SettingsProvider, useSettings } from '../SettingsContext'

vi.mock('sonner', () => ({
  toast: { loading: vi.fn(() => 'toast'), success: vi.fn(), error: vi.fn() },
}))

import { toast } from 'sonner'

type Gate = { promise: Promise<void>; open: () => void }
function gate(): Gate {
  let open: () => void = () => {}
  const promise = new Promise<void>((resolve) => {
    open = resolve
  })
  return { promise, open }
}

// What the tab would send if it saved right now, and what each save sent.
let draft = ''
let saved: string[] = []
let handlerGate: Gate | null = null

function FakeTab(): ReactElement {
  const { registerSaveHandler, unregisterSaveHandler, triggerSave, setCurrentTabId } =
    useSettings()
  useEffect(() => {
    setCurrentTabId('system')
    registerSaveHandler('system', async () => {
      saved.push(draft)
      if (handlerGate) await handlerGate.promise
    })
    return () => unregisterSaveHandler('system')
  }, [registerSaveHandler, unregisterSaveHandler, setCurrentTabId])
  return <button onClick={triggerSave}>edit</button>
}

// Like the real tabs: the handler is a closure over the tab's values, and the
// tab registers a new one on every change and unregisters when it unmounts.
function ClosureTab({ value }: { value: string }): ReactElement {
  const { registerSaveHandler, unregisterSaveHandler, triggerSave, setCurrentTabId } =
    useSettings()
  useEffect(() => {
    setCurrentTabId('system')
  }, [setCurrentTabId])
  useEffect(() => {
    registerSaveHandler('system', async () => {
      saved.push(value)
      if (handlerGate) await handlerGate.promise
    })
    return () => unregisterSaveHandler('system')
  }, [value, registerSaveHandler, unregisterSaveHandler])
  return <button onClick={triggerSave}>edit</button>
}

function edit(value: string): void {
  draft = value
  fireEvent.click(screen.getByRole('button', { name: 'edit' }))
}

async function wait(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms)
  })
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  draft = ''
  saved = []
  handlerGate = null
})

afterEach(() => {
  vi.useRealTimers()
})

describe('SettingsProvider autosave', () => {
  it('saves an edit whose debounce fires during the post-save refresh', async () => {
    const refresh = gate()
    const onSaved = vi.fn(() => refresh.promise)
    render(
      <SettingsProvider onSaved={onSaved}>
        <FakeTab />
      </SettingsProvider>,
    )

    edit('first')
    await wait(1000)
    expect(saved).toEqual(['first'])
    expect(onSaved).toHaveBeenCalledTimes(1)

    // The refresh is still out when the second edit's debounce fires.
    edit('second')
    await wait(1000)

    await act(async () => {
      refresh.open()
    })
    await wait(0)
    expect(saved).toEqual(['first', 'second'])
    expect(onSaved).toHaveBeenCalledTimes(2)
    expect(toast.success).toHaveBeenCalledTimes(2)
  })

  it('saves an edit whose debounce fires while the save itself is still out', async () => {
    handlerGate = gate()
    const slowSave = handlerGate
    render(
      <SettingsProvider>
        <FakeTab />
      </SettingsProvider>,
    )

    edit('first')
    await wait(1000)
    expect(saved).toEqual(['first'])

    edit('second')
    await wait(1000)
    expect(saved).toEqual(['first'])

    handlerGate = null
    await act(async () => {
      slowSave.open()
    })
    await wait(0)
    expect(saved).toEqual(['first', 'second'])
  })

  it('folds several edits made during one save into a single follow-up save', async () => {
    handlerGate = gate()
    const slowSave = handlerGate
    render(
      <SettingsProvider>
        <FakeTab />
      </SettingsProvider>,
    )

    edit('first')
    await wait(1000)
    edit('second')
    await wait(1000)
    edit('third')
    await wait(1000)

    handlerGate = null
    await act(async () => {
      slowSave.open()
    })
    await wait(0)
    // The handler reads the tab's latest state, so one more save covers both.
    expect(saved).toEqual(['first', 'third'])
  })

  it("still saves a queued edit after its tab unmounts, with the tab's last values", async () => {
    handlerGate = gate()
    const slowSave = handlerGate
    const page = (value: string | null): ReactElement => (
      <SettingsProvider>{value !== null && <ClosureTab value={value} />}</SettingsProvider>
    )
    const { rerender } = render(page('first'))

    fireEvent.click(screen.getByRole('button', { name: 'edit' }))
    await wait(1000)
    expect(saved).toEqual(['first'])

    // An edit queues behind the slow save, then the user switches tabs.
    rerender(page('second'))
    fireEvent.click(screen.getByRole('button', { name: 'edit' }))
    await wait(1000)
    rerender(page(null))

    handlerGate = null
    await act(async () => {
      slowSave.open()
    })
    await wait(0)
    expect(saved).toEqual(['first', 'second'])
    expect(toast.success).toHaveBeenCalledTimes(2)
    expect(toast.error).not.toHaveBeenCalled()
  })

  it('still saves an edit whose debounce fires after its tab unmounted', async () => {
    const page = (value: string | null): ReactElement => (
      <SettingsProvider>{value !== null && <ClosureTab value={value} />}</SettingsProvider>
    )
    const { rerender } = render(page('first'))

    fireEvent.click(screen.getByRole('button', { name: 'edit' }))
    rerender(page(null))
    await wait(1000)

    expect(saved).toEqual(['first'])
    expect(toast.success).toHaveBeenCalledTimes(1)
  })
})
