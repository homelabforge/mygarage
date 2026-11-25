import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { Button, Field, Input, Textarea, registerDecimal } from './ui'
import CurrencyInput from './common/CurrencyInput'
import type {
  SpotRentalBilling,
  SpotRentalBillingCreate,
  SpotRentalBillingUpdate
} from '../types/spotRental'
import {
  makeSpotRentalBillingSchema,
  type SpotRentalBillingFormData
} from '../schemas/spotRentalBilling'
import { useCreateBillingEntry, useUpdateBillingEntry } from '../hooks/queries/useSpotRentals'
import { formatDateForInput } from '../utils/dateUtils'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { useOnUserEdit } from '../hooks/useOnUserEdit'

interface BillingEntryFormProps {
  vin: string
  rentalId: number
  billing?: SpotRentalBilling
  onClose: () => void
  onSuccess: () => void
}

export default function BillingEntryForm({
  vin,
  rentalId,
  billing,
  onClose,
  onSuccess
}: BillingEntryFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!billing
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateBillingEntry(vin, rentalId)
  const updateMutation = useUpdateBillingEntry(vin, rentalId)

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeSpotRentalBillingSchema(t), [t])

  const {
    register,
    handleSubmit,
    setValue,
    subscribe,
    formState: { errors, isSubmitting }
  } = useForm<SpotRentalBillingFormData>({
    resolver: zodResolver(schema) as Resolver<SpotRentalBillingFormData>,
    defaultValues: {
      billing_date: formatDateForInput(billing?.billing_date),
      monthly_rate: billing?.monthly_rate != null ? Number(billing.monthly_rate) : undefined,
      electric: billing?.electric != null ? Number(billing.electric) : undefined,
      water: billing?.water != null ? Number(billing.water) : undefined,
      waste: billing?.waste != null ? Number(billing.waste) : undefined,
      total: billing?.total != null ? Number(billing.total) : undefined,
      notes: billing?.notes ?? undefined
    }
  })

  // Suggest the total from the amounts, but only when the user edits one.
  // Recomputing on open overwrote a total adjusted by hand.
  useOnUserEdit(subscribe, ['monthly_rate', 'electric', 'water', 'waste'], (values) => {
    const calculatedTotal =
      (values.monthly_rate || 0) + (values.electric || 0) + (values.water || 0) + (values.waste || 0)
    if (calculatedTotal > 0) {
      setValue('total', calculatedTotal)
    }
  })

  const onSubmit = async (data: SpotRentalBillingFormData) => {
    try {
      setError(null)

      const payload: SpotRentalBillingCreate | SpotRentalBillingUpdate = {
        billing_date: data.billing_date,
        monthly_rate: data.monthly_rate ?? null,
        electric: data.electric ?? null,
        water: data.water ?? null,
        waste: data.waste ?? null,
        total: data.total ?? null,
        notes: data.notes ?? null
      }

      if (isEdit && billing) {
        await updateMutation.mutateAsync({ id: billing.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as SpotRentalBillingCreate)
      }

      onSuccess()
      onClose()
    } catch (err: unknown) {
      console.error('Failed to save billing entry:', err)
      setError(getActionErrorMessage(err, t('billing.saveAction')))
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('billing.editTitle') : t('billing.createTitle')}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="billing-entry-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="billing-entry-form" onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="space-y-6">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <Field id="billing_date" label={t('billing.billingDate')} required error={errors.billing_date}>
            <Input id="billing_date" type="date" {...register('billing_date')} invalid={!!errors.billing_date} disabled={isSubmitting} />
          </Field>

          <Field id="monthly_rate" label={t('spotRental.monthlyRate')} error={errors.monthly_rate}>
            <CurrencyInput
              id="monthly_rate"
              {...registerDecimal(register, 'monthly_rate')}
              placeholder="0.00"
              invalid={!!errors.monthly_rate}
              disabled={isSubmitting}
            />
          </Field>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Field id="electric" label={t('billingEntryForm.electric')} error={errors.electric}>
              <CurrencyInput
                id="electric"
                {...registerDecimal(register, 'electric')}
                placeholder="0.00"
                invalid={!!errors.electric}
                disabled={isSubmitting}
              />
            </Field>

            <Field id="water" label={t('billingEntryForm.water')} error={errors.water}>
              <CurrencyInput
                id="water"
                {...registerDecimal(register, 'water')}
                placeholder="0.00"
                invalid={!!errors.water}
                disabled={isSubmitting}
              />
            </Field>

            <Field id="waste" label={t('billingEntryForm.waste')} error={errors.waste}>
              <CurrencyInput
                id="waste"
                {...registerDecimal(register, 'waste')}
                placeholder="0.00"
                invalid={!!errors.waste}
                disabled={isSubmitting}
              />
            </Field>
          </div>

          <Field id="total" label={t('common:total')} hint={t('billing.autoCalculatedHint')} error={errors.total}>
            <CurrencyInput
              id="total"
              {...registerDecimal(register, 'total')}
              placeholder={t('billingEntryForm.autoCalculatedPlaceholder')}
              readOnly
            />
          </Field>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea
              id="notes"
              rows={4}
              {...register('notes')}
              placeholder={t('billing.notesPlaceholder')}
              invalid={!!errors.notes}
              disabled={isSubmitting}
            />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
