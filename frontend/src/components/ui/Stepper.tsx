import { Check } from 'lucide-react'
import Mono from './Mono'

export interface StepperStep {
  number: number
  /** Already translated by the caller. */
  title: string
  description?: string
}

interface StepperProps {
  steps: StepperStep[]
  /** 1-based index of the active step. */
  current: number
  /** Accessible name for the progress bar. Already translated by the caller. */
  label: string
  /** Spoken position, e.g. "Step 2 of 4". Already translated by the caller —
   *  the component does not compose it, because an English template literal
   *  here would be untranslated shipped copy and a hardcoded-strings finding.
   *  Omitted entirely when not supplied. */
  valueText?: string
}

/**
 * Wizard progress indicator. Extracted from two near-identical copies in
 * VehicleWizard and VehicleTransferWizard.
 *
 * Neither original announced anything to assistive tech. This exposes the
 * position via role="progressbar" with aria-valuenow/valuemin/valuemax —
 * role="progressbar", not role="group", because those are range-widget
 * attributes and every AT ignores them on a group. A test using
 * toHaveAttribute would not have caught that (it reads the DOM, not the
 * accessibility tree) and eslint-plugin-jsx-a11y is not installed here.
 */
export default function Stepper({ steps, current, label, valueText }: StepperProps) {
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuenow={current}
      aria-valuemin={1}
      aria-valuemax={steps.length}
      aria-valuetext={valueText}
      className="flex items-center gap-2"
    >
      {steps.map((step, index) => {
        const state =
          step.number < current ? 'complete' : step.number === current ? 'current' : 'upcoming'

        return (
          <div key={step.number} className="flex flex-1 items-center gap-2">
            <div
              data-testid={`step-${step.number}`}
              data-state={state}
              className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
                state === 'complete'
                  ? 'bg-success text-on-status'
                  : state === 'current'
                    ? 'bg-(--accent-solid) text-(--accent-on-solid)'
                    : 'bg-surface-2 text-text-mute'
              }`}
            >
              {state === 'complete' ? (
                <Check aria-hidden="true" className="h-4 w-4" />
              ) : (
                <Mono size="xs" weight="semibold">{step.number}</Mono>
              )}
            </div>
            <span
              className={`hidden text-sm sm:inline ${
                state === 'upcoming' ? 'text-text-mute' : 'text-text'
              }`}
            >
              {step.title}
            </span>
            {index < steps.length - 1 ? (
              <div
                aria-hidden="true"
                className={`h-0.5 flex-1 ${step.number < current ? 'bg-success' : 'bg-border'}`}
              />
            ) : null}
          </div>
        )
      })}
    </div>
  )
}
