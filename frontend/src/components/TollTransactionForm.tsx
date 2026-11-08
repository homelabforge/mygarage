import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import CurrencyInput from './common/CurrencyInput'
import { Button, Field, Input, Select, Textarea, registerDecimal } from './ui'
import type { TollTransaction, TollTransactionCreate, TollTransactionUpdate, TollTag } from '../types/toll'
import { makeTollTransactionSchema, type TollTransactionFormData } from '../schemas/tollTransaction'
import { useCreateTollTransaction, useUpdateTollTransaction } from '../hooks/queries/useTollRecords'
import { applyServerErrors } from '../utils/apiFormErrors'
import { actionErrorMessage } from '../utils/httpErrorHandler'
import { formatDateForInput } from '@/utils/dateUtils'

interface TollTransactionFormProps {
  vin: string
  tollTags: TollTag[]
  transaction?: TollTransaction
  onClose: () => void
  onSuccess: () => void
}

export default function TollTransactionForm({ vin, tollTags, transaction, onClose, onSuccess }: TollTransactionFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!transaction
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateTollTransaction(vin)
  const updateMutation = useUpdateTollTransaction(vin)

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeTollTransactionSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError: setFieldError,
  } = useForm<TollTransactionFormData>({
    resolver: zodResolver(schema) as Resolver<TollTransactionFormData>,
    defaultValues: {
      transaction_date: transaction?.date || formatDateForInput(),
      amount: transaction?.amount != null ? Number(transaction.amount) : undefined,
      location: transaction?.location || '',
      toll_tag_id: transaction?.toll_tag_id ?? undefined,
      notes: transaction?.notes || '',
    },
  })

  const onSubmit = async (data: TollTransactionFormData) => {
    setError(null)

    try {
      // Zod has already validated and coerced amount and toll_tag_id - no parseFloat/parseInt needed!
      const payload: TollTransactionCreate | TollTransactionUpdate = {
        transaction_date: data.transaction_date,
        amount: data.amount,
        location: data.location,
        // Null for "None (manual payment)": the update route skips keys that
        // aren't sent, so an undefined here left the old tag linked.
        toll_tag_id: data.toll_tag_id ?? null,
        notes: data.notes,
      }

      if (!isEdit) {
        (payload as TollTransactionCreate).vin = vin
      }

      if (isEdit) {
        await updateMutation.mutateAsync({ id: transaction.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as TollTransactionCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { parsed, attached, unhandled } = applyServerErrors<TollTransactionFormData>(setFieldError, err, [
        'transaction_date',
        'amount',
        'location',
        'toll_tag_id',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(actionErrorMessage(parsed, t('toll.saveTransactionAction')))
      }
    }
  }

  const activeTollTags = tollTags.filter(tag => tag.status === 'active')

  return (
    <FormModalWrapper
      title={isEdit ? t('toll.editTransactionTitle') : t('toll.createTransactionTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('tollTransactionForm.cancel')}
          </Button>
          <Button type="submit" form="toll-transaction-form" variant="primary" icon={Save} loading={isSubmitting} disabled={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('toll.updateTransaction') : t('toll.addTransaction')}
          </Button>
        </>
      }
    >
        <form id="toll-transaction-form" onSubmit={handleSubmit(onSubmit as Parameters<typeof handleSubmit>[0])} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="transaction_date" label={t('common:date')} required error={errors.transaction_date}>
              <Input id="transaction_date" type="date" {...register('transaction_date')} invalid={!!errors.transaction_date} disabled={isSubmitting} />
            </Field>

            <Field id="amount" label={t('common:amount')} required error={errors.amount}>
              <CurrencyInput
                id="amount"
                {...registerDecimal(register, 'amount')}
                placeholder="0.00"
                invalid={!!errors.amount}
                disabled={isSubmitting}
              />
            </Field>
          </div>

          <Field id="location" label={t('toll.location')} required error={errors.location}>
            <Input id="location" type="text" {...register('location')} placeholder={t('toll.locationPlaceholder')} invalid={!!errors.location} disabled={isSubmitting} />
          </Field>

          <Field id="toll_tag_id" label={t('toll.tollTag')} error={errors.toll_tag_id}>
            <Select
              id="toll_tag_id"
              {...register('toll_tag_id', { valueAsNumber: true })}
              disabled={isSubmitting}
              invalid={!!errors.toll_tag_id}
              placeholder={t('toll.noneManualPayment')}
              options={activeTollTags.map((tag) => ({ value: String(tag.id), label: `${tag.toll_system} - ${tag.tag_number}` }))}
            />
            {activeTollTags.length === 0 && (
              <p className="text-xs text-text-mute mt-1">{t('toll.noActiveTollTags')}</p>
            )}
          </Field>

          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('toll.transactionNotesPlaceholder')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
