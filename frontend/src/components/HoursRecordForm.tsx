import { useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { HoursRecord, HoursRecordCreate, HoursRecordUpdate } from '../types/hours'
import { makeHoursRecordSchema, type HoursRecordFormData } from '../schemas/hours'
import { useCreateHoursRecord, useUpdateHoursRecord } from '../hooks/queries/useHoursRecords'
import { formatDateForInput } from '../utils/dateUtils'
import { useFormSubmit } from '../hooks/useFormSubmit'
import { Button, Field, Input, NumberInput, Textarea, registerDecimal } from './ui'

interface HoursRecordFormProps {
  vin: string
  record?: HoursRecord
  onClose: () => void
  onSuccess: () => void
}

/**
 * Engine-hours analog of OdometerRecordForm. Engine hours are dimensionless
 * -- there is no UnitPreference/UnitConverter round-trip here, unlike
 * odometer_km's `canonicalFromUnitField` conversion: the entered value is
 * submitted as-is.
 */
export default function HoursRecordForm({ vin, record, onClose, onSuccess }: HoursRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const createMutation = useCreateHoursRecord(vin)
  const updateMutation = useUpdateHoursRecord(vin)

  const submitFn = useCallback(async (data: HoursRecordFormData) => {
    const payload: HoursRecordCreate | HoursRecordUpdate = {
      vin,
      date: data.date,
      engine_hours: data.engine_hours,
      notes: data.notes,
    }

    if (isEdit) {
      await updateMutation.mutateAsync({ id: record.id, ...payload })
    } else {
      await createMutation.mutateAsync(payload as HoursRecordCreate)
    }
  }, [isEdit, vin, record, createMutation, updateMutation])

  const { error, handleSubmit: onSubmit } = useFormSubmit(submitFn, {
    onSuccess,
    onClose,
    action: t('hours.saveAction'),
  })

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeHoursRecordSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<HoursRecordFormData>({
    resolver: zodResolver(schema) as Resolver<HoursRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      engine_hours: (() => {
        const stored = record?.engine_hours
        const num = stored == null ? undefined : (typeof stored === 'string' ? parseFloat(stored) : stored)
        return num == null || isNaN(num) ? undefined : num
      })(),
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper
      title={isEdit ? t('hours.editTitle') : t('hours.createTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>{t('common:cancel')}</Button>
          <Button type="submit" form="hours-record-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="hours-record-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <Field id="date" label={t('common:date')} required error={errors.date}>
            <Input id="date" type="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
          </Field>

          <Field id="engine_hours" label={t('common:engineHours')} unit="hr" required error={errors.engine_hours}>
            <NumberInput
              id="engine_hours"
              {...registerDecimal(register, 'engine_hours')}
              placeholder="812.4"
              invalid={!!errors.engine_hours}
              disabled={isSubmitting}
            />
          </Field>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('hours.notesPlaceholder')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
