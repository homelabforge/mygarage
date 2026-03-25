import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { TollTag, TollTagCreate, TollTagUpdate } from '../types/toll'
import { tollTagSchema, type TollTagFormData, TOLL_SYSTEMS } from '../schemas/tollTag'
import { FormError } from './FormError'
import { useCreateTollTag, useUpdateTollTag } from '../hooks/queries/useTollRecords'

interface TollTagFormProps {
  vin: string
  tag?: TollTag
  onClose: () => void
  onSuccess: () => void
}

export default function TollTagForm({ vin, tag, onClose, onSuccess }: TollTagFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!tag
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateTollTag(vin)
  const updateMutation = useUpdateTollTag(vin)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<TollTagFormData>({
    resolver: zodResolver(tollTagSchema),
    defaultValues: {
      toll_system: (tag?.toll_system as (typeof TOLL_SYSTEMS)[number]) ?? 'EZ TAG',
      tag_number: tag?.tag_number || '',
      status: (tag?.status as 'active' | 'inactive') || 'active',
      notes: tag?.notes || '',
    },
  })

  const onSubmit = async (data: TollTagFormData) => {
    setError(null)

    try {
      const payload: TollTagCreate | TollTagUpdate = {
        toll_system: data.toll_system,
        tag_number: data.tag_number,
        status: data.status,
        notes: data.notes,
      }

      if (!isEdit) {
        (payload as TollTagCreate).vin = vin
      }

      if (isEdit) {
        await updateMutation.mutateAsync({ id: tag.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as TollTagCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common:error'))
    }
  }

  return (
    <FormModalWrapper title={isEdit ? t('toll.editTagTitle') : t('toll.createTagTitle')} onClose={onClose}>
        <form onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="toll_system" className="block text-sm font-medium text-garage-text mb-1">
                {t('toll.tollSystem')} <span className="text-danger">*</span>
              </label>
              <select
                id="toll_system"
                {...register('toll_system')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                  errors.toll_system ? 'border-red-500' : 'border-garage-border'
                }`}
                disabled={isSubmitting}
              >
                <option value="">{t('toll.selectTollSystem')}</option>
                {TOLL_SYSTEMS.map((system) => (
                  <option key={system} value={system}>{system}</option>
                ))}
              </select>
              <FormError error={errors.toll_system} />
            </div>

            <div>
              <label htmlFor="tag_number" className="block text-sm font-medium text-garage-text mb-1">
                {t('toll.tagNumber')} <span className="text-danger">*</span>
              </label>
              <input
                type="text"
                id="tag_number"
                {...register('tag_number')}
                className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text font-mono ${
                  errors.tag_number ? 'border-red-500' : 'border-garage-border'
                }`}
                placeholder="e.g., 0012345678"
                disabled={isSubmitting}
              />
              <FormError error={errors.tag_number} />
            </div>
          </div>

          <div>
            <label htmlFor="status" className="block text-sm font-medium text-garage-text mb-1">
              {t('common:status')}
            </label>
            <select
              id="status"
              {...register('status')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.status ? 'border-red-500' : 'border-garage-border'
              }`}
              disabled={isSubmitting}
            >
              <option value="active">{t('common:active')}</option>
              <option value="inactive">{t('common:inactive')}</option>
            </select>
            <FormError error={errors.status} />
          </div>

          <div>
            <label htmlFor="notes" className="block text-sm font-medium text-garage-text mb-1">
              {t('common:notes')}
            </label>
            <textarea
              id="notes"
              {...register('notes')}
              className={`w-full px-3 py-2 border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text ${
                errors.notes ? 'border-red-500' : 'border-garage-border'
              }`}
              rows={3}
              placeholder={t('toll.tagNotesPlaceholder')}
              disabled={isSubmitting}
            />
            <FormError error={errors.notes} />
          </div>

          <div className="flex justify-end gap-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="btn btn-primary rounded-lg transition-colors"
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50"
              disabled={isSubmitting}
            >
              <Save className="w-4 h-4" />
              {isSubmitting ? t('common:saving') : isEdit ? t('toll.updateTag') : t('toll.addTag')}
            </button>
          </div>
        </form>
    </FormModalWrapper>
  )
}
