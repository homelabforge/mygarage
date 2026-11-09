import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import CurrencyInput from './common/CurrencyInput'
import { Button, Field, Input, Select, Textarea, registerDecimal } from './ui'
import type { TaxRecord, TaxRecordCreate, TaxRecordUpdate } from '../types/tax'
import { asTaxType, makeTaxRecordSchema, type TaxRecordFormData, taxTypeOptions } from '../schemas/tax'
import { useCreateTaxRecord, useUpdateTaxRecord } from '../hooks/queries/useTaxRecords'
import { formatDateForInput } from '../utils/dateUtils'
import { applyServerErrors } from '../utils/apiFormErrors'
import { actionErrorMessage } from '../utils/httpErrorHandler'
import { useResolvedCountry } from '../hooks/useResolvedCountry'
import { useCountryProfile } from '../hooks/queries/useCountryProfile'
import api from '../services/api'

interface TaxRecordFormProps {
  vin: string
  record?: TaxRecord
  onClose: () => void
  onSuccess: () => void
}

export default function TaxRecordForm({ vin, record, onClose, onSuccess }: TaxRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateTaxRecord(vin)
  const updateMutation = useUpdateTaxRecord(vin)
  // #211 — the country whose tax types come first, with their national
  // names: the vehicle's registration country, then the person's, then the
  // instance's. No country, or a country without a profile: the plain list.
  const [vehicleRegistrationCountry, setVehicleRegistrationCountry] = useState<string | null>(null)
  const country = useResolvedCountry({ registration_country: vehicleRegistrationCountry })
  const { data: countryProfile } = useCountryProfile(country)
  useEffect(() => {
    let cancelled = false
    void api
      .get(`/vehicles/${vin}`)
      .then((response) => {
        if (!cancelled) setVehicleRegistrationCountry(response.data?.registration_country ?? null)
      })
      .catch(() => {
        if (!cancelled) setVehicleRegistrationCountry(null)
      })
    return () => {
      cancelled = true
    }
  }, [vin])
  const typeOptions = useMemo(
    () => taxTypeOptions(t, countryProfile?.taxes?.types, countryProfile?.taxes?.names),
    [t, countryProfile]
  )

  const onSubmit = async (data: TaxRecordFormData) => {
    setError(null)

    try {
      // On edit an emptied field must be null, or the update keeps the old value.
      const cleared = isEdit ? null : undefined
      const payload: TaxRecordCreate | TaxRecordUpdate = {
        vin,
        date: data.date,
        tax_type: data.tax_type || cleared,
        amount: data.amount,
        renewal_date: data.renewal_date || cleared,
        notes: data.notes,
      }

      if (isEdit) {
        await updateMutation.mutateAsync({ id: record.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as TaxRecordCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { parsed, attached, unhandled } = applyServerErrors<TaxRecordFormData>(setFieldError, err, [
        'date',
        'tax_type',
        'amount',
        'renewal_date',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(actionErrorMessage(parsed, t('tax.saveAction')))
      }
    }
  }

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeTaxRecordSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<TaxRecordFormData>({
    resolver: zodResolver(schema) as Resolver<TaxRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      // A record from before migration 146 carries a display string: its code.
      tax_type: asTaxType(record?.tax_type) ?? undefined,
      amount: record?.amount != null ? parseFloat(String(record.amount)) : undefined,
      renewal_date: record?.renewal_date ? formatDateForInput(record.renewal_date) : '',
      notes: record?.notes || '',
    },
  })

  return (
    <FormModalWrapper
      title={isEdit ? t('tax.editTitle') : t('tax.createTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="tax-record-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="tax-record-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="date" label={t('tax.datePaid')} required error={errors.date}>
              <Input id="date" type="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
            </Field>

            <Field id="tax_type" label={t('taxRecordForm.type')} error={errors.tax_type}>
              <Select
                id="tax_type"
                {...register('tax_type')}
                disabled={isSubmitting}
                invalid={!!errors.tax_type}
                placeholder={t('tax.selectType')}
                options={typeOptions}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field id="amount" label={t('common:amount')} required error={errors.amount}>
              <CurrencyInput
                id="amount"
                {...registerDecimal(register, 'amount')}
                placeholder="85.50"
                invalid={!!errors.amount}
                disabled={isSubmitting}
              />
            </Field>

            <Field id="renewal_date" label={t('tax.renewalDate')} error={errors.renewal_date} hint={t('tax.renewalDateHint')}>
              <Input id="renewal_date" type="date" {...register('renewal_date')} invalid={!!errors.renewal_date} disabled={isSubmitting} />
            </Field>
          </div>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('common:additionalNotes')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
