import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Section from '../gallery/Section'

describe('gallery Section', () => {
  it('renders its title and children', () => {
    render(
      <Section title="Button">
        <button>press</button>
      </Section>,
    )
    expect(screen.getByRole('heading', { name: 'Button' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'press' })).toBeInTheDocument()
  })
})
