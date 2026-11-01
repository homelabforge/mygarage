import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import VendorSearch from './VendorSearch'
import { Button, Field, Input, NumberInput, Select, Textarea, registerDecimal } from './ui'
import type { FinancingRecord, FinancingRecordCreate, FinancingRecordUpdate } from '../types/financing'
import { makeFinancingRecordSchema, type FinancingRecordFormData, FINANCING_CATEGORIES } from '../schemas/financing'
import { useCreateFinancingRecord, useUpdateFinancingRecord } from '../hooks/queries/useFinancingRecords'
import { formatDateForInput } from '../utils/dateUtils'
import { applyServerErrors } from '../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

interface FinancingRecordFormProps {
  vin: string
  record?: FinancingRecord
  onClose: () => void
  onSuccess: () => void
}

export default function FinancingRecordForm({ vin, record, onClose, onSuccess }: FinancingRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateFinancingRecord(vin)
  const updateMutation = useUpdateFinancingRecord(vin)

  const onSubmit = async (data: FinancingRecordFormData) => {
    setError(null)

    try {
      const payload: FinancingRecordCreate | FinancingRecordUpdate = {
        vin,
        date: data.date,
        category: data.category,
        amount: data.amount,
        vendor_id: data.vendor_id ?? null,
        notes: data.notes,
      }

      if (isEdit) {
        await updateMutation.mutateAsync({ id: record.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as FinancingRecordCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // A non-422 failure (network, 500) attaches no field errors.
      const { attached, unhandled } = applyServerErrors<FinancingRecordFormData>(setFieldError, err, [
        'date',
        'category',
        'amount',
        'vendor_id',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('financing.saveAction')))
      }
    }
  }

  // Messages are baked in at construction, so rebuild the schema on language change.
  const schema = useMemo(() => makeFinancingRecordSchema(t), [t])

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<FinancingRecordFormData>({
    resolver: zodResolver(schema) as Resolver<FinancingRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      category: record?.category ?? undefined,
      amount: record?.amount != null ? parseFloat(String(record.amount)) : undefined,
      vendor_id: record?.vendor_id ?? undefined,
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper
      title={isEdit ? t('financing.editTitle') : t('financing.createTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="financing-record-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="financing-record-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="date" label={t('financing.date')} required error={errors.date}>
              <Input id="date" type="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
            </Field>

            <Field id="category" label={t('financing.category')} required error={errors.category}>
              <Select
                id="category"
                {...register('category')}
                disabled={isSubmitting}
                invalid={!!errors.category}
                placeholder={t('financing.selectCategory')}
                options={FINANCING_CATEGORIES.map((option) => ({
                  value: option.value,
                  label: t(option.labelKey),
                }))}
              />
            </Field>
          </div>

          <Field id="amount" label={t('common:amount')} required error={errors.amount}>
            <div className="relative">
              <CurrencyInputPrefix />
              <NumberInput
                id="amount"
                {...registerDecimal(register, 'amount')}
                placeholder="450.00"
                invalid={!!errors.amount}
                disabled={isSubmitting}
                className="pl-7"
              />
            </div>
          </Field>

          <div>
            <label htmlFor="financing-lender" className="mb-1 block text-sm font-medium text-text">{t('financing.lender')}</label>
            <VendorSearch
              id="financing-lender"
              value={watch('vendor_id')}
              onSelect={(vendor) => setValue('vendor_id', vendor?.id ?? undefined)}
              placeholder={t('financing.lenderSearchPlaceholder')}
              disabled={isSubmitting}
            />
          </div>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('common:additionalNotes')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
