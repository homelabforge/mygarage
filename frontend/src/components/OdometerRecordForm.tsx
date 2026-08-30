import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { OdometerRecord, OdometerRecordCreate, OdometerRecordUpdate } from '../types/odometer'
import { makeOdometerRecordSchema, type OdometerRecordFormData } from '../schemas/odometer'
import { useCreateOdometerRecord, useUpdateOdometerRecord } from '../hooks/queries/useOdometerRecords'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { canonicalFromUnitField, seedUnitField, type UnitFieldOrigin } from '../utils/unitFormat'
import { readNumber } from '../utils/decimalSafe'
import { formatDateForInput } from '../utils/dateUtils'
import { useFormSubmit } from '../hooks/useFormSubmit'
import { Button, Field, Input, NumberInput, Textarea, registerDecimal } from './ui'

interface OdometerRecordFormProps {
  vin: string
  record?: OdometerRecord
  onClose: () => void
  onSuccess: () => void
}

export default function OdometerRecordForm({ vin, record, onClose, onSuccess }: OdometerRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const createMutation = useCreateOdometerRecord(vin)
  const updateMutation = useUpdateOdometerRecord(vin)
  const u = useUnitFormat()

  /**
   * The canonical origin of the reading, seeded once.
   *
   * The reading used to be read and written on `useUnitPreference().system`,
   * which spec D8 collapses from VOLUME: a `{volume: 'L', distance: 'mi'}`
   * account typed miles into a field labelled `km` and stored them verbatim.
   * On a form whose whole subject is the odometer that is the entire record.
   *
   * The origin is what stops an untouched save from rewriting it: 72420.5 km
   * displays as 45000 mi and 45000 mi converts back to 72420.3 km. Seeded
   * through a lazy `useState` for the same reason `defaultValues` is computed
   * once; an origin that moved on re-render would stop being one.
   */
  const [odometerOrigin] = useState<UnitFieldOrigin>(() =>
    seedUnitField(readNumber(record?.odometer_km), u.distance)
  )

  const submitFn = useCallback(async (data: OdometerRecordFormData) => {
    // Back through `units.distance`, and an untouched field returns the
    // canonical value it was seeded from rather than a re-conversion of a
    // rounded display. `readNumber` also absorbs `registerDecimal`'s
    // INVALID_NUMBER symbol, which throws on every implicit coercion.
    const odometerTyped = readNumber(data.odometer_km)
    const payload: OdometerRecordCreate | OdometerRecordUpdate = {
      vin,
      date: data.date,
      odometer_km:
        canonicalFromUnitField(String(odometerTyped ?? ''), odometerOrigin, u.distance) ??
        undefined,
      notes: data.notes,
    }

    if (isEdit) {
      await updateMutation.mutateAsync({ id: record.id, ...payload })
    } else {
      await createMutation.mutateAsync(payload as OdometerRecordCreate)
    }
  }, [isEdit, vin, record, odometerOrigin, u.distance, createMutation, updateMutation])

  const { error, handleSubmit: onSubmit } = useFormSubmit(submitFn, {
    onSuccess,
    onClose,
    action: t('odometer.saveAction'),
  })

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeOdometerRecordSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<OdometerRecordFormData>({
    resolver: zodResolver(schema) as Resolver<OdometerRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      odometer_km: readNumber(odometerOrigin.display),
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper
      title={isEdit ? t('odometer.editTitle') : t('odometer.createTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>{t('odometerRecordForm.cancel')}</Button>
          <Button type="submit" form="odometer-record-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="odometer-record-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <Field id="date" label={t('common:date')} required error={errors.date}>
            <Input id="date" type="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
          </Field>

          <Field id="odometer_km" label={t('common:mileage')} unit={u.distance.label} required error={errors.odometer_km}>
            <NumberInput
              id="odometer_km"
              {...registerDecimal(register, 'odometer_km')}
              /* One example reading (72420 km) rendered in the client's own
                 distance unit, rather than one of two literals chosen by a
                 collapsed system. It reproduces both shipped hints exactly
                 (72420 km, and 72420 / 1.60934 = 44999.81 shown as 45000) and
                 needs no new branch for a distance token added later. */
              placeholder={u.distance.toInputValue(72420)}
              invalid={!!errors.odometer_km}
              disabled={isSubmitting}
            />
          </Field>

          <Field id="notes" label={t('odometerRecordForm.notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('odometer.notesPlaceholder')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
