import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import ProgressMeter from '../ProgressMeter'

describe('ProgressMeter', () => {
  it('exposes its share as a named progressbar', () => {
    render(<ProgressMeter label="Oil change" percent={42.4} />)
    const bar = screen.getByRole('progressbar', { name: 'Oil change' })
    expect(bar).toHaveAttribute('aria-valuenow', '42')
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '100')
  })

  it('announces the words it is given in place of the bare number', () => {
    render(<ProgressMeter label="Oil change" percent={90} valueText="1,240 mi left" />)
    expect(screen.getByRole('progressbar', { name: 'Oil change' })).toHaveAttribute(
      'aria-valuetext',
      '1,240 mi left',
    )
  })

  it('clamps past due to a full bar and below the start to an empty one', () => {
    render(
      <>
        <ProgressMeter label="Over" percent={125} />
        <ProgressMeter label="Under" percent={-10} />
      </>,
    )
    const over = screen.getByRole('progressbar', { name: 'Over' })
    const under = screen.getByRole('progressbar', { name: 'Under' })
    expect(over).toHaveAttribute('aria-valuenow', '100')
    expect(over.firstElementChild).toHaveStyle({ width: '100%' })
    expect(under).toHaveAttribute('aria-valuenow', '0')
    expect(under.firstElementChild).toHaveStyle({ width: '0%' })
  })

  it('fills in the tone it is given, accent by default', () => {
    render(
      <>
        <ProgressMeter label="Default" percent={50} />
        <ProgressMeter label="Late" percent={50} tone="danger" />
        <ProgressMeter label="Soon" percent={50} tone="warning" />
        <ProgressMeter label="Quiet" percent={50} tone="muted" />
      </>,
    )
    const fill = (name: string): Element | null =>
      screen.getByRole('progressbar', { name }).firstElementChild
    expect(fill('Default')).toHaveClass('bg-(--accent-solid)')
    expect(fill('Late')).toHaveClass('bg-danger')
    expect(fill('Soon')).toHaveClass('bg-warning')
    expect(fill('Quiet')).toHaveClass('bg-text-mute')
  })
})
