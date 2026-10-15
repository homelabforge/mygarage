import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import MakeSelect from '../MakeSelect'

function MakeSelectWrapper({ initial = '' }: { initial?: string }) {
  const [val, setVal] = useState(initial)
  return <MakeSelect id="make-select" value={val} onChange={setVal} />
}

describe('MakeSelect', () => {
  it('renders input with placeholder and value', () => {
    render(<MakeSelect id="make-select" value="Fiat" onChange={vi.fn()} />)
    const input = screen.getByRole('combobox')
    expect(input).toHaveValue('Fiat')
  })

  it('renders brand logo inside input prefix when make is selected', () => {
    render(<MakeSelect id="make-select" value="Fiat" onChange={vi.fn()} />)
    const img = screen.getByRole('img')
    expect(img).toHaveAttribute('src', expect.stringContaining('fiat.png'))
  })

  it('opens dropdown on focus and lists makes', () => {
    render(<MakeSelectWrapper />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(screen.getByText('Alfa Romeo')).toBeInTheDocument()
    expect(screen.getByText('Ford')).toBeInTheDocument()
  })

  it('filters makes based on typed query', () => {
    render(<MakeSelectWrapper />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'mitsu' } })

    expect(screen.getByText('Mitsubishi')).toBeInTheDocument()
    expect(screen.queryByText('Alfa Romeo')).not.toBeInTheDocument()
  })

  it('selects a make when clicked from dropdown', () => {
    const onChange = vi.fn()
    render(<MakeSelect id="make-select" value="" onChange={onChange} />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)

    const fordOption = screen.getByText('Ford')
    fireEvent.click(fordOption)

    expect(onChange).toHaveBeenCalledWith('Ford')
  })

  it('allows custom make entry', () => {
    const onChange = vi.fn()
    render(<MakeSelect id="make-select" value="" onChange={onChange} />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'Custom Supercar' } })

    const customOption = screen.getByText('"Custom Supercar"')
    fireEvent.click(customOption)

    expect(onChange).toHaveBeenCalledWith('Custom Supercar')
  })

  it('supports keyboard navigation and enter to select', () => {
    const onChange = vi.fn()
    render(<MakeSelect id="make-select" value="" onChange={onChange} />)
    const input = screen.getByRole('combobox')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'ford' } })

    // ArrowDown to highlight, Enter to select
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    fireEvent.keyDown(input, { key: 'Enter' })

    expect(onChange).toHaveBeenCalledWith('Ford')
  })

  it('clears value when clear button is clicked', () => {
    const onChange = vi.fn()
    render(<MakeSelect id="make-select" value="Ford" onChange={onChange} />)

    const clearButton = screen.getByRole('button', { name: /clear/i })
    fireEvent.click(clearButton)

    expect(onChange).toHaveBeenCalledWith('')
  })
})
