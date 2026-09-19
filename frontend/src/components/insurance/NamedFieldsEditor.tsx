import { Plus, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  useFieldArray,
  useWatch,
  type Control,
  type FieldErrors,
  type UseFormRegister,
} from 'react-hook-form'
import type { InsuranceFormData } from '../../schemas/insurance'
import { Chip, IconButton, Input } from '../ui'

type FieldsPath = 'fields' | `vehicles.${number}.fields`
type NamedFieldErrors = FieldErrors<InsuranceFormData>['fields']

interface NamedFieldsEditorProps {
  control: Control<InsuranceFormData>
  register: UseFormRegister<InsuranceFormData>
  name: FieldsPath
  /** i18n keys of labels offered as one-tap chips. */
  suggestions: readonly string[]
  disabled?: boolean
  /** Distinguishes the inputs of several editors on one form. */
  idPrefix: string
  /** This array's validation errors, so an incomplete row says why Save did nothing. */
  errors?: NamedFieldErrors
}

/**
 * User-named label/value pairs. Most policies carry the same handful of
 * details, so the common ones are one tap; anything else is typed.
 */
export default function NamedFieldsEditor({
  control,
  register,
  name,
  suggestions,
  disabled = false,
  idPrefix,
  errors,
}: NamedFieldsEditorProps) {
  const { t } = useTranslation('forms')
  const { fields, append, remove } = useFieldArray({ control, name })
  // The LIVE values, not the field-array snapshot: a user who retypes a
  // suggested label by hand should stop being offered it, and one who renames
  // a chip's label should get the chip back.
  const live = useWatch({ control, name }) ?? []
  const used = new Set(live.map((field) => (field?.label ?? '').trim()))
  const offered = suggestions.map((key) => t(key)).filter((label) => !used.has(label))

  return (
    <div className="space-y-2">
      {fields.map((field, index) => {
        const rowError = errors?.[index]
        const incomplete = !!(rowError?.label || rowError?.value)
        return (
          <div key={field.id}>
            <div className="flex gap-2 items-start">
              <Input
                id={`${idPrefix}-label-${index}`}
                aria-label={t('insurance.fieldLabel')}
                placeholder={t('insurance.fieldLabel')}
                maxLength={60}
                {...register(`${name}.${index}.label` as const)}
                invalid={!!rowError?.label}
                disabled={disabled}
                className="flex-1"
              />
              <Input
                id={`${idPrefix}-value-${index}`}
                aria-label={t('insurance.fieldValue')}
                placeholder={t('insurance.fieldValue')}
                maxLength={255}
                {...register(`${name}.${index}.value` as const)}
                invalid={!!rowError?.value}
                disabled={disabled}
                className="flex-1"
              />
              <IconButton
                icon={X}
                label={t('insurance.removeField')}
                variant="ghost"
                size="sm"
                disabled={disabled}
                onClick={() => remove(index)}
              />
            </div>
            {incomplete && (
              <p role="alert" className="text-xs text-danger mt-1">
                {t('insurance.fieldIncomplete')}
              </p>
            )}
          </div>
        )
      })}
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          {offered.map((label) => (
            <Chip key={label} icon={Plus} onClick={() => append({ label, value: '' })}>
              {label}
            </Chip>
          ))}
          <Chip icon={Plus} tone="accent" onClick={() => append({ label: '', value: '' })}>
            {t('insurance.addCustomField')}
          </Chip>
        </div>
      )}
    </div>
  )
}
