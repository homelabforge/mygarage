import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { Recall, RecallCreate, RecallUpdate } from '../types/recall'
import { makeRecallSchema, type RecallFormData } from '../schemas/recall'
import { useCreateRecallRecord, useUpdateRecallRecord } from '../hooks/queries/useRecallRecords'
import { Button, Field, Input, Textarea, Checkbox } from './ui'
import { applyServerErrors } from '../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

interface RecallFormProps {
  vin: string
  recall?: Recall
  onClose: () => void
  onSuccess: () => void
}

export default function RecallForm({ vin, recall, onClose, onSuccess }: RecallFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!recall
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateRecallRecord(vin)
  const updateMutation = useUpdateRecallRecord(vin)

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeRecallSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<RecallFormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      nhtsa_campaign_number: recall?.nhtsa_campaign_number || '',
      component: recall?.component || '',
      summary: recall?.summary || '',
      consequence: recall?.consequence || '',
      remedy: recall?.remedy || '',
      date_announced: recall?.date_announced || '',
      is_resolved: recall?.is_resolved ?? false,
      notes: recall?.notes || '',
    },
  })

  const onSubmit = async (data: RecallFormData) => {
    setError(null)

    try {
      // On edit an emptied date must be null, or the update keeps the old one.
      const cleared = isEdit ? null : undefined
      const payload: RecallCreate | RecallUpdate = {
        nhtsa_campaign_number: data.nhtsa_campaign_number,
        component: data.component,
        summary: data.summary,
        consequence: data.consequence,
        remedy: data.remedy,
        date_announced: data.date_announced || cleared,
        is_resolved: data.is_resolved,
        notes: data.notes,
      }

      if (!isEdit) {
        (payload as RecallCreate).vin = vin
      }

      if (isEdit) {
        await updateMutation.mutateAsync({ id: recall.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as RecallCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show. The resolved checkbox isn't
      // listed: it has nowhere to show an error, so its errors go to the banner.
      const { attached, unhandled } = applyServerErrors<RecallFormData>(setFieldError, err, [
        'nhtsa_campaign_number',
        'component',
        'summary',
        'consequence',
        'remedy',
        'date_announced',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('recall.saveAction')))
      }
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('recall.editTitle') : t('recall.createTitle')}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>{t('recallForm.cancel')}</Button>
          <Button type="submit" form="recall-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('recall.updateRecall') : t('recall.addRecall')}
          </Button>
        </>
      }
    >
        <form id="recall-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="nhtsa_campaign_number" label={t('recall.nhtsaCampaignNumber')} error={errors.nhtsa_campaign_number}>
              <Input id="nhtsa_campaign_number" type="text" mono {...register('nhtsa_campaign_number')} placeholder="e.g., 23V123000" invalid={!!errors.nhtsa_campaign_number} disabled={isSubmitting} />
            </Field>
            <Field id="date_announced" label={t('recall.dateAnnounced')} error={errors.date_announced}>
              <Input id="date_announced" type="date" {...register('date_announced')} invalid={!!errors.date_announced} disabled={isSubmitting} />
            </Field>
          </div>

          <Field id="component" label={t('recall.component')} required error={errors.component}>
            <Input id="component" type="text" {...register('component')} placeholder={t('recallForm.componentPlaceholder')} invalid={!!errors.component} disabled={isSubmitting} />
          </Field>

          <Field id="summary" label={t('recall.summary')} required error={errors.summary}>
            <Textarea id="summary" rows={3} {...register('summary')} placeholder={t('recall.summaryPlaceholder')} invalid={!!errors.summary} disabled={isSubmitting} />
          </Field>

          <Field id="consequence" label={t('recall.consequence')} error={errors.consequence}>
            <Textarea id="consequence" rows={2} {...register('consequence')} placeholder={t('recall.consequencePlaceholder')} invalid={!!errors.consequence} disabled={isSubmitting} />
          </Field>

          <Field id="remedy" label={t('recall.remedy')} error={errors.remedy}>
            <Textarea id="remedy" rows={2} {...register('remedy')} placeholder={t('recall.remedyPlaceholder')} invalid={!!errors.remedy} disabled={isSubmitting} />
          </Field>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={2} {...register('notes')} placeholder={t('common:additionalNotes')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>

          <Checkbox id="is_resolved" label={t('recall.markAsResolved')} {...register('is_resolved')} disabled={isSubmitting} />
        </form>
    </FormModalWrapper>
  )
}
