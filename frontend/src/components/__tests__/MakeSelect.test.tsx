import { describe, it, expect, vi } from 'vitest'
import { useState } from 'react'
import { render, screen, fireEvent } from '../../__tests__/test-utils'
import MakeSelect from '../MakeSelect'
import ModelSelect from '../ModelSelect'

function Harness({ initial = '', onChange }: { initial?: string; onChange?: (v: string) => void }) {
  const [value, setValue] = useState(initial)
  return (
    <>
      <label htmlFor="make">Make</label>
      <MakeSelect
        id="make"
        value={value}
        onChange={(v) => {
          setValue(v)
          onChange?.(v)
        }}
      />
    </>
  )
}

describe('MakeSelect (#219)', () => {
  it('is a labelled combobox', () => {
    render(<Harness />)
    expect(screen.getByRole('combobox', { name: 'Make' })).toBeInTheDocument()
  })

  it('suggests catalog makes with their logos and picks one by keyboard', () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    const box = screen.getByRole('combobox', { name: 'Make' })
    fireEvent.change(box, { target: { value: 'mits' } })

    const option = screen.getByRole('option', { name: /Mitsubishi/ })
    expect(option.querySelector('img')).toHaveAttribute('src', expect.stringContaining('/brand-logos/mitsubishi.png'))
    fireEvent.keyDown(box, { key: 'ArrowDown' })
    fireEvent.keyDown(box, { key: 'Enter' })

    expect(onChange).toHaveBeenLastCalledWith('Mitsubishi')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('keeps free text it does not know', () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'KZ-RV' } })
    expect(onChange).toHaveBeenLastCalledWith('KZ-RV')
    expect(screen.getByRole('combobox')).toHaveValue('KZ-RV')
  })

  it('matches without diacritics', () => {
    render(<Harness />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'skoda' } })
    expect(screen.getByRole('option', { name: /Škoda/ })).toBeInTheDocument()
  })

  it('shows the logo beside a known make and a letter badge for an unknown one', () => {
    const { unmount } = render(<Harness initial="Ram" />)
    expect(screen.getByTestId('make-logo').querySelector('img')).toHaveAttribute(
      'src',
      expect.stringContaining('/brand-logos/ram.png'),
    )
    unmount()
    render(<Harness initial="KZ-RV" />)
    expect(screen.queryByTestId('make-logo')).not.toBeInTheDocument()
  })

  it('falls back to a letter badge when the image fails', () => {
    render(<Harness initial="Ram" />)
    const img = screen.getByTestId('make-logo').querySelector('img') as HTMLImageElement
    fireEvent.error(img)
    expect(screen.getByTestId('make-logo')).toHaveTextContent('R')
    expect(screen.getByTestId('make-logo').querySelector('img')).toBeNull()
  })
})

describe('ModelSelect (#219)', () => {
  function ModelHarness({ make }: { make: string }) {
    const [value, setValue] = useState('')
    return (
      <>
        <label htmlFor="model">Model</label>
        <ModelSelect id="model" make={make} value={value} onChange={setValue} />
      </>
    )
  }

  it("suggests the make's models", () => {
    render(<ModelHarness make="Mitsubishi" />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Model' }), { target: { value: 'mir' } })
    expect(screen.getByRole('option', { name: 'Mirage' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Mirage G4' })).toBeInTheDocument()
  })

  it('reads the make loosely (decoded or typed in capitals)', () => {
    render(<ModelHarness make="MITSUBISHI" />)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'mir' } })
    expect(screen.getByRole('option', { name: 'Mirage' })).toBeInTheDocument()
  })

  it('suggests nothing for a make it does not know, and keeps the text', () => {
    render(<ModelHarness make="KZ-RV" />)
    const box = screen.getByRole('combobox')
    fireEvent.change(box, { target: { value: 'Durango' } })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(box).toHaveValue('Durango')
  })
})
