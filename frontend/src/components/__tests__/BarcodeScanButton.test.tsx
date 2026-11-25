/**
 * The manual-entry fallback. jsdom has no BarcodeDetector, same as Linux
 * Chromium, so a click goes straight to the typed-code dialog.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BarcodeScanButton from '../BarcodeScanButton'

const field = (): HTMLElement => screen.getByRole('textbox', { name: 'supplies.barcode' })

async function openManual(): Promise<void> {
  await userEvent.click(screen.getByRole('button', { name: 'supplies.scanBarcode' }))
  await screen.findByRole('dialog', { name: 'supplies.barcodeManualPrompt' })
}

async function closed(): Promise<void> {
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
}

describe('BarcodeScanButton manual entry', () => {
  it('OK hands over the trimmed code', async () => {
    const onScan = vi.fn()
    render(<BarcodeScanButton onScan={onScan} />)

    await openManual()
    await userEvent.type(field(), '  0123456789  ')
    await userEvent.click(screen.getByRole('button', { name: 'common:ok' }))

    await closed()
    expect(onScan).toHaveBeenCalledExactlyOnceWith('0123456789')
  })

  it('Cancel hands over nothing', async () => {
    const onScan = vi.fn()
    render(<BarcodeScanButton onScan={onScan} />)

    await openManual()
    await userEvent.type(field(), '0123456789')
    await userEvent.click(screen.getByRole('button', { name: 'common:cancel' }))

    await closed()
    expect(onScan).not.toHaveBeenCalled()
  })

  it('OK on an empty or blank field hands over nothing', async () => {
    const onScan = vi.fn()
    render(<BarcodeScanButton onScan={onScan} />)

    await openManual()
    await userEvent.type(field(), '   ')
    await userEvent.click(screen.getByRole('button', { name: 'common:ok' }))

    await closed()
    expect(onScan).not.toHaveBeenCalled()
  })

  // React events bubble through portals, so the dialog's submit would reach
  // the supply form around the button and save the supply.
  it('Enter and OK never submit the form the button sits in', async () => {
    const onScan = vi.fn()
    const outerSubmit = vi.fn((e: React.FormEvent) => e.preventDefault())
    render(
      <form onSubmit={outerSubmit}>
        <BarcodeScanButton onScan={onScan} />
      </form>,
    )

    await openManual()
    await userEvent.type(field(), 'ABC-1{Enter}')
    await closed()
    expect(onScan).toHaveBeenLastCalledWith('ABC-1')

    await openManual()
    await userEvent.type(field(), 'ABC-2')
    await userEvent.click(screen.getByRole('button', { name: 'common:ok' }))
    await closed()
    expect(onScan).toHaveBeenLastCalledWith('ABC-2')

    expect(onScan).toHaveBeenCalledTimes(2)
    expect(outerSubmit).not.toHaveBeenCalled()
  })
})
