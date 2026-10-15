import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ModelSelect from '../ModelSelect'

function ModelSelectWrapper({ make, initial = '' }: { make?: string; initial?: string }) {
  const [val, setVal] = useState(initial)
  return <ModelSelect id="model-select" make={make} value={val} onChange={setVal} />
}

describe('ModelSelect', () => {
  it('renders input with value', () => {
    render(<ModelSelect id="model-select" make="Fiat" value="500" onChange={vi.fn()} />)
    const input = screen.getByRole('combobox')
    expect(input).toHaveValue('500')
  })

  it('lists models for selected make', () => {
    render(<ModelSelectWrapper make="Fiat" />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getByText('500')).toBeInTheDocument()
    expect(screen.getByText('Panda')).toBeInTheDocument()
  })

  it('filters models based on typed search query', () => {
    render(<ModelSelectWrapper make="Fiat" />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'pan' } })

    expect(screen.getByText('Panda')).toBeInTheDocument()
    expect(screen.queryByText('500')).not.toBeInTheDocument()
  })

  it('selects a model when clicked from dropdown', () => {
    const onChange = vi.fn()
    render(<ModelSelect id="model-select" make="Ford" value="" onChange={onChange} />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    const fiestaOption = screen.getByText('Fiesta')
    fireEvent.click(fiestaOption)

    expect(onChange).toHaveBeenCalledWith('Fiesta')
  })

  it('allows custom model entry', () => {
    const onChange = vi.fn()
    render(<ModelSelect id="model-select" make="Ford" value="" onChange={onChange} />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'Custom Model GT' } })

    const customOption = screen.getByText('"Custom Model GT"')
    fireEvent.click(customOption)

    expect(onChange).toHaveBeenCalledWith('Custom Model GT')
  })

  it('clears value when clear button is clicked', () => {
    const onChange = vi.fn()
    render(<ModelSelect id="model-select" make="Ford" value="Fiesta" onChange={onChange} />)

    const clearButton = screen.getByRole('button', { name: /clear/i })
    fireEvent.click(clearButton)

    expect(onChange).toHaveBeenCalledWith('')
  })
})
