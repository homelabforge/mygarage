import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  useWatch,
  type Control,
  type FieldErrors,
  type UseFormRegister,
  type UseFormSetValue,
} from 'react-hook-form'
import type { CoverageFormData, InsuranceFormData } from '../../schemas/insurance'
import type { CoverageKey } from '../../types/insurance'
import { COVERAGES, coverageLayout, coverageSlots } from '../../constants/insuranceCoverages'
import { Button, Checkbox, Field, NumberInput, registerDecimal } from '../ui'

type CoveragesPath = `vehicles.${number}.coverages`
type CoverageErrors = NonNullable<
  NonNullable<FieldErrors<InsuranceFormData>['vehicles']>[number]
>['coverages']

interface CoverageEditorProps {
  control: Control<InsuranceFormData>
  register: UseFormRegister<InsuranceFormData>
  setValue: UseFormSetValue<InsuranceFormData>
  name: CoveragesPath
  disabled?: boolean
  /** Distinguishes the inputs of several vehicles' editors on one form. */
  idPrefix: string
  /** This vehicle's coverage errors, already narrowed by the caller. */
  errors?: CoverageErrors
  /** The country profile's coverages, shown first in its order; the rest of
   *  the catalogue folds behind « more coverages » (#211). */
  preferredKeys?: readonly string[]
}

/**
 * The standard coverage checklist: one row per catalogue coverage, always the
 * same rows for every vehicle on every policy.
 *
 * TICKING THE BOX is what says the coverage is carried; the amounts are how
 * much, and every one of them is optional. So roadside assistance with nothing
 * typed is a complete, meaningful answer, and a coverage left unticked is
 * simply not on the policy.
 *
 * An unticked row stays one line. The amounts appear only once a coverage is
 * on the policy, which keeps the catalogue short on screen when a vehicle
 * carries four of them. Which amounts those are comes from `coverageSlots`,
 * never from a branch here, so the form can never offer an input the API
 * would reject or miss one it expects.
 *
 * ORDER. The form's array keeps the catalogue order, so a row is at the same
 * index for every vehicle; what changes with the country is only which rows
 * are shown first. With a profile, its coverages come first and the others
 * sit behind a « more coverages » button, opened on its own when one of them
 * is carried (a parsed North American page on a French account, say).
 */
export default function CoverageEditor({
  control,
  register,
  setValue,
  name,
  disabled = false,
  idPrefix,
  errors,
  preferredKeys,
}: CoverageEditorProps) {
  const { t } = useTranslation('forms')
  const rows = (useWatch({ control, name }) ?? []) as CoverageFormData[]
  const { shown, more } = coverageLayout(preferredKeys)
  const positionOf = new Map(rows.map((row, position) => [row?.coverage_key, position]))
  const hiddenCarried = more.filter((key) => {
    const position = positionOf.get(key)
    return position !== undefined && !!rows[position]?.included
  }).length
  const [showMore, setShowMore] = useState(hiddenCarried > 0)
  useEffect(() => {
    if (hiddenCarried > 0) setShowMore(true)
  }, [hiddenCarried])

  const renderRow = (key: CoverageKey) => {
    const position = positionOf.get(key)
    const meta = COVERAGES[key]
    if (position === undefined || !meta) return null
    const row = rows[position]
    const included = !!row?.included
    const rowErrors = errors?.[position]
    const { onChange, ...tick } = register(`${name}.${position}.included`)

    return (
      <div key={key} className={`rounded-lg px-3 py-2 ${included ? 'bg-surface-2' : ''}`}>
        <Checkbox
          id={`${idPrefix}-${key}`}
          label={t(meta.labelKey)}
          disabled={disabled}
          {...tick}
          onChange={async (event) => {
            await onChange(event)
            // Untick and the amounts go with it. Left behind, an invalid
            // one keeps blocking the save from a row that is no longer
            // on screen to show its error.
            if (!event.target.checked) {
              for (const [slotName] of coverageSlots(key)) {
                setValue(`${name}.${position}.${slotName}`, undefined, {
                  shouldValidate: true,
                })
              }
            }
          }}
        />
        {included && (
          <div className="mt-2 grid gap-3 grid-cols-[repeat(auto-fill,minmax(9rem,1fr))]">
            {coverageSlots(key).map(([slotName, slot]) => {
              const id = `${idPrefix}-${key}-${slotName}`
              const error = rowErrors?.[slotName]?.message
              return (
                <Field key={slotName} id={id} label={t(slot.labelKey)} error={error}>
                  <NumberInput
                    id={id}
                    {...registerDecimal(register, `${name}.${position}.${slotName}`)}
                    invalid={!!error}
                    disabled={disabled}
                  />
                </Field>
              )
            })}
            {meta.hintKey && !meta.primary && (
              <p className="text-xs text-text-mute self-end pb-2">{t(meta.hintKey)}</p>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <fieldset className="space-y-1">
      <legend className="text-xs font-semibold uppercase tracking-wide text-text-mute mb-2">
        {t('insurance.coverages')}
      </legend>
      {shown.map(renderRow)}
      {more.length > 0 && (
        <div className="pt-1">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={showMore}
            onClick={() => setShowMore((open) => !open)}
          >
            {showMore
              ? t('insuranceCoverages.lessCoverages')
              : t('insuranceCoverages.moreCoverages', { count: more.length })}
          </Button>
          {showMore && <div className="space-y-1 mt-1">{more.map(renderRow)}</div>}
        </div>
      )}
    </fieldset>
  )
}
