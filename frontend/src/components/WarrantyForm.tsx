import { useTranslation } from 'react-i18next'
import { useCallback, useMemo, useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { Button, Field, Input, NumberInput, Select, Textarea, registerDecimal } from './ui'
import type { WarrantyRecord, WarrantyRecordCreate, WarrantyRecordUpdate } from '../types/warranty'
import { makeWarrantySchema, type WarrantyFormData, WARRANTY_TYPES } from '../schemas/warranty'
import { useCreateWarrantyRecord, useUpdateWarrantyRecord } from '../hooks/queries/useWarrantyRecords'
import { formatDateForInput } from '../utils/dateUtils'
import { useFormSubmit } from '../hooks/useFormSubmit'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { canonicalFromUnitField, seedUnitField, type UnitFieldOrigin } from '../utils/unitFormat'
import { readNumber } from '../utils/decimalSafe'

interface WarrantyFormProps {
  vin: string
  record?: WarrantyRecord
  onClose: () => void
  onSuccess: () => void
}

export default function WarrantyForm({ vin, record, onClose, onSuccess }: WarrantyFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const createMutation = useCreateWarrantyRecord(vin)
  const updateMutation = useUpdateWarrantyRecord(vin)
  const u = useUnitFormat()

  /**
   * The canonical origin of the mileage limit, seeded once.
   *
   * The limit used to be read and written on `useUnitPreference().system`,
   * which spec D8 collapses from VOLUME: a `{volume: 'L', distance: 'mi'}`
   * account entered miles into a field labelled `km` and stored them verbatim.
   * `u.distance` is the token the account actually chose.
   *
   * The origin is what stops an untouched save from rewriting the record:
   * 96560 km displays as 60000 mi and 60000 mi converts back to 96560.4 km, so
   * re-converting the display would move a limit the user only looked at.
   * Seeded through a lazy `useState` for the same reason `defaultValues` is
   * computed once; an origin that moved on re-render would stop being one.
   */
  const [mileageLimitOrigin] = useState<UnitFieldOrigin>(() =>
    seedUnitField(readNumber(record?.mileage_limit_km), u.distance)
  )

  const submitFn = useCallback(async (data: WarrantyFormData) => {
    // Back through `units.distance`, and an untouched field returns the
    // canonical value it was seeded from rather than a re-conversion of a
    // rounded display. `readNumber` also absorbs `registerDecimal`'s
    // INVALID_NUMBER symbol, which throws on every implicit coercion.
    const limitTyped = readNumber(data.mileage_limit_km)
    const payload: WarrantyRecordCreate | WarrantyRecordUpdate = {
      warranty_type: data.warranty_type,
      provider: data.provider,
      start_date: data.start_date,
      end_date: data.end_date,
      mileage_limit_km:
        canonicalFromUnitField(String(limitTyped ?? ''), mileageLimitOrigin, u.distance) ??
        undefined,
      coverage_details: data.coverage_details,
      policy_number: data.policy_number,
      notes: data.notes,
    }

    if (isEdit) {
      await updateMutation.mutateAsync({ id: record.id, ...payload })
    } else {
      await createMutation.mutateAsync(payload as WarrantyRecordCreate)
    }
  }, [isEdit, record, mileageLimitOrigin, u.distance, createMutation, updateMutation])

  const { error, handleSubmit: onSubmit } = useFormSubmit(submitFn, {
    onSuccess,
    onClose,
    action: t('warranty.saveAction'),
  })

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeWarrantySchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<WarrantyFormData>({
    resolver: zodResolver(schema) as Resolver<WarrantyFormData>,
    defaultValues: {
      warranty_type: record?.warranty_type || '',
      provider: record?.provider || '',
      start_date: formatDateForInput(record?.start_date),
      end_date: formatDateForInput(record?.end_date === '' || record?.end_date === null ? undefined : record?.end_date),
      mileage_limit_km: readNumber(mileageLimitOrigin.display),
      coverage_details: record?.coverage_details || '',
      policy_number: record?.policy_number || '',
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper
      title={isEdit ? t('warranty.editTitle') : t('warranty.createTitle')}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="warranty-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="warranty-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="warranty_type" label={t('warranty.warrantyType')} required error={errors.warranty_type}>
              <Select
                id="warranty_type"
                {...register('warranty_type')}
                disabled={isSubmitting}
                invalid={!!errors.warranty_type}
                placeholder={t('common:selectType')}
                options={WARRANTY_TYPES.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
              />
            </Field>

            <Field id="provider" label={t('insurance.provider')} error={errors.provider}>
              <Input id="provider" type="text" {...register('provider')} placeholder={t('warrantyForm.providerPlaceholder')} invalid={!!errors.provider} disabled={isSubmitting} />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field id="start_date" label={t('common:startDate')} required error={errors.start_date}>
              <Input id="start_date" type="date" {...register('start_date')} invalid={!!errors.start_date} disabled={isSubmitting} />
            </Field>
            <Field id="end_date" label={t('common:endDate')} error={errors.end_date}>
              <Input id="end_date" type="date" {...register('end_date')} invalid={!!errors.end_date} disabled={isSubmitting} />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field id="mileage_limit_km" label={t('warranty.mileageLimit')} unit={u.distance.label} error={errors.mileage_limit_km}>
              <NumberInput id="mileage_limit_km" {...registerDecimal(register, 'mileage_limit_km')} placeholder={t('warrantyForm.mileageLimitPlaceholder')} invalid={!!errors.mileage_limit_km} disabled={isSubmitting} />
            </Field>
            <Field id="policy_number" label={t('insurance.policyNumber')} error={errors.policy_number}>
              <Input id="policy_number" type="text" {...register('policy_number')} placeholder={t('warrantyForm.policyNumberPlaceholder')} invalid={!!errors.policy_number} disabled={isSubmitting} />
            </Field>
          </div>

          <Field id="coverage_details" label={t('warranty.coverageDetails')} error={errors.coverage_details}>
            <Textarea id="coverage_details" rows={3} {...register('coverage_details')} placeholder={t('warranty.coverageDetailsPlaceholder')} invalid={!!errors.coverage_details} disabled={isSubmitting} />
          </Field>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={2} {...register('notes')} placeholder={t('common:additionalNotes')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
