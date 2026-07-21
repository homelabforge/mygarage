import { describe, it, expect } from 'vitest'
import { render, screen } from '../../../__tests__/test-utils'
import Stepper from '../Stepper'

const STEPS = [
  { number: 1, title: 'VIN' },
  { number: 2, title: 'Details' },
  { number: 3, title: 'Review' },
]

describe('Stepper', () => {
  it('renders every step title', () => {
    render(<Stepper steps={STEPS} current={2} label="Add vehicle progress" />)
    for (const step of STEPS) {
      expect(screen.getByText(step.title)).toBeInTheDocument()
    }
  })

  it('announces progress to assistive tech', () => {
    // progressbar, not group: aria-valuenow/min/max are range-widget
    // attributes and are ignored on role="group". Querying BY the role is
    // what makes this assertion non-vacuous — toHaveAttribute alone reads
    // the DOM and would pass against a role that ignores the attributes.
    render(
      <Stepper
        steps={STEPS}
        current={2}
        label="Add vehicle progress"
        valueText="Step 2 of 3"
      />,
    )
    const bar = screen.getByRole('progressbar', { name: 'Add vehicle progress' })
    expect(bar).toHaveAttribute('aria-valuenow', '2')
    expect(bar).toHaveAttribute('aria-valuemin', '1')
    expect(bar).toHaveAttribute('aria-valuemax', '3')
    expect(bar).toHaveAttribute('aria-valuetext', 'Step 2 of 3')
  })

  it('marks completed steps', () => {
    render(<Stepper steps={STEPS} current={2} label="Progress" />)
    expect(screen.getByTestId('step-1')).toHaveAttribute('data-state', 'complete')
    expect(screen.getByTestId('step-2')).toHaveAttribute('data-state', 'current')
    expect(screen.getByTestId('step-3')).toHaveAttribute('data-state', 'upcoming')
  })
})
