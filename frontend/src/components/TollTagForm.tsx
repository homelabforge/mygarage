import { useTranslation } from 'react-i18next'
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useForm, type UseFormSetError } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import { Button, Field, Input, Select, Textarea } from './ui'
import type { TollTag, TollTagCreate, TollTagUpdate } from '../types/toll'
import { makeTollTagSchema, type TollTagFormData, TOLL_SYSTEM_MAX } from '../schemas/tollTag'
import {
  TOLL_OTHER,
  choiceForCountry,
  guessTollCountry,
  initialTollSelection,
  listedTollSystem,
  selectedTollSystem,
  tollCountryOptions,
  tollSystemsFor,
  usesOtherName,
} from '../utils/tollSystems'
import { languageToLocale } from '../constants/i18n'
import { useCurrencyPreference } from '../hooks/useCurrencyPreference'
import { useCreateTollTag, useUpdateTollTag } from '../hooks/queries/useTollRecords'
import { applyServerErrors } from '../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

interface TollTagFormProps {
  vin: string
  tag?: TollTag
  onClose: () => void
  onSuccess: () => void
}

export default function TollTagForm({ vin, tag, onClose, onSuccess }: TollTagFormProps) {
  const { t, i18n } = useTranslation('forms')
  const isEdit = !!tag
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateTollTag(vin)
  const updateMutation = useUpdateTollTag(vin)
  const { currencyCode } = useCurrencyPreference()
  const locale = languageToLocale(i18n.language)

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it (no fetch, no
  // reset()), so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeTollTagSchema(t), [t])

  // useForm reads defaultValues once, so only the first render's guess counts.
  const initial = initialTollSelection(tag?.toll_system, guessTollCountry(currencyCode, i18n.language))

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    getValues,
    setFocus,
    clearErrors,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<TollTagFormData>({
    resolver: zodResolver(schema),
    defaultValues: {
      toll_country: initial.country,
      toll_system: initial.choice,
      // Seeded even while hidden. The name field mounts later, and an
      // unseeded field would submit nothing instead of the saved name.
      toll_system_other: initial.otherName,
      tag_number: tag?.tag_number || '',
      status: (tag?.status as 'active' | 'inactive') || 'active',
      notes: tag?.notes || '',
    },
  })

  const country = watch('toll_country')
  const choice = watch('toll_system')
  const otherName = watch('toll_system_other')
  const showName = usesOtherName({ country, choice })
  const listedName = showName ? listedTollSystem(otherName) : null
  const countryOptions = useMemo(() => tollCountryOptions(locale), [locale])
  const systems = useMemo(() => tollSystemsFor(country, locale), [country, locale])
  const otherOption = { value: TOLL_OTHER, label: t('tollSystems.other') }
  const systemLocked = country === '' || country === TOLL_OTHER

  // Focus the name field when the user picks Other, not when an edit opens on it.
  const focusName = useRef(false)
  useEffect(() => {
    if (showName && focusName.current) {
      focusName.current = false
      setFocus('toll_system_other')
    }
  }, [showName, setFocus])

  const onSubmit = async (data: TollTagFormData) => {
    setError(null)
    const selection = { country: data.toll_country, choice: data.toll_system, otherName: data.toll_system_other }

    try {
      const payload: TollTagCreate | TollTagUpdate = {
        // Country only filters the list. The system is what's saved.
        toll_system: selectedTollSystem(selection),
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
      // The API only knows toll_system. If the user typed it, the error goes under the name field.
      const setServerError: UseFormSetError<TollTagFormData> = (name, fieldError, options) =>
        setFieldError(name === 'toll_system' && usesOtherName(selection) ? 'toll_system_other' : name, fieldError, options)
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<TollTagFormData>(setServerError, err, [
        'toll_system',
        'tag_number',
        'status',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('toll.saveTagAction')))
      }
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('toll.editTagTitle') : t('toll.createTagTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('tollTagForm.cancel')}
          </Button>
          <Button type="submit" form="toll-tag-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('toll.updateTag') : t('toll.addTag')}
          </Button>
        </>
      }
    >
        <form id="toll-tag-form" onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="toll_country" label={t('toll.country')} required error={errors.toll_country}>
              <Select
                id="toll_country"
                {...register('toll_country', {
                  onChange: (e: ChangeEvent<HTMLSelectElement>) => {
                    const kept = choiceForCountry(getValues('toll_system'), e.target.value)
                    setValue('toll_system', kept)
                    clearErrors(['toll_country', 'toll_system', 'toll_system_other'])
                    focusName.current = !showName && usesOtherName({ country: e.target.value, choice: kept })
                  },
                })}
                disabled={isSubmitting}
                invalid={!!errors.toll_country}
                placeholder={t('toll.selectCountry')}
                options={[...countryOptions, otherOption]}
              />
            </Field>

            <Field id="toll_system" label={t('toll.tollSystem')} required error={errors.toll_system}>
              <Select
                id="toll_system"
                {...register('toll_system', {
                  onChange: (e: ChangeEvent<HTMLSelectElement>) => {
                    clearErrors(['toll_system', 'toll_system_other'])
                    focusName.current = !showName && e.target.value === TOLL_OTHER
                  },
                })}
                disabled={isSubmitting || systemLocked}
                invalid={!!errors.toll_system}
                placeholder={
                  country === '' ? t('toll.chooseCountryFirst') : country === TOLL_OTHER ? undefined : t('toll.selectTollSystem')
                }
                options={
                  country === ''
                    ? []
                    : country === TOLL_OTHER
                      ? [otherOption]
                      : [...systems.map((s) => ({ value: s, label: s })), otherOption]
                }
              />
            </Field>
          </div>

          {showName && (
            <Field
              id="toll_system_other"
              label={t('toll.tollSystemName')}
              required
              error={errors.toll_system_other}
              hint={listedName ? t('toll.tollSystemSavesAs', { name: listedName }) : t('toll.tollSystemNameHint')}
            >
              <Input
                id="toll_system_other"
                type="text"
                maxLength={TOLL_SYSTEM_MAX}
                {...register('toll_system_other')}
                placeholder={t('toll.tollSystemNamePlaceholder')}
                invalid={!!errors.toll_system_other}
                disabled={isSubmitting}
              />
            </Field>
          )}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field id="tag_number" label={t('toll.tagNumber')} required error={errors.tag_number}>
              <Input id="tag_number" type="text" mono {...register('tag_number')} placeholder="e.g., 0012345678" invalid={!!errors.tag_number} disabled={isSubmitting} />
            </Field>

            <Field id="status" label={t('common:status')} error={errors.status}>
              <Select
                id="status"
                {...register('status')}
                disabled={isSubmitting}
                invalid={!!errors.status}
                options={[
                  { value: 'active', label: t('common:active') },
                  { value: 'inactive', label: t('common:inactive') },
                ]}
              />
            </Field>
          </div>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('toll.tagNotesPlaceholder')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
