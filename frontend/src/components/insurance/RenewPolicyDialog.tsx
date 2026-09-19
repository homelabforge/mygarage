/**
 * Enter a policy's next term. Deliberately short: a renewal notice changes the
 * premium and the dates and nothing else, so the vehicles, coverages and named
 * fields carry over untouched. It can be entered the day the notice arrives;
 * the new term reads "Upcoming" until it starts.
 */

import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from '../FormModalWrapper'
import { Button, Field, Input, NumberInput, registerDecimal } from '../ui'
import { makeRenewSchema, type RenewFormData } from '../../schemas/insurance'
import { useRenewInsurancePolicy } from '../../hooks/queries/useInsuranceRecords'
import { addDaysToIsoDate, formatDateForInput } from '../../utils/dateUtils'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import type { InsurancePolicy } from '../../types/insurance'

interface RenewPolicyDialogProps {
  policy: InsurancePolicy
  onClose: () => void
  onSuccess: () => void
}

const DAY_MS = 86_400_000

export default function RenewPolicyDialog({ policy, onClose, onSuccess }: RenewPolicyDialogProps) {
  const { t } = useTranslation('forms')
  const renewMutation = useRenewInsurancePolicy()
  const schema = useMemo(() => makeRenewSchema(t), [t])

  // The next term starts where this one ends and runs the same length.
  const start = formatDateForInput(policy.end_date)
  const termDays = Math.round(
    (Date.parse(`${policy.end_date}T00:00:00Z`) - Date.parse(`${policy.start_date}T00:00:00Z`)) /
      DAY_MS
  )

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RenewFormData>({
    resolver: zodResolver(schema) as Resolver<RenewFormData>,
    defaultValues: {
      start_date: start,
      end_date: addDaysToIsoDate(start, termDays),
      premium_amount: policy.premium_amount != null ? Number(policy.premium_amount) : undefined,
    },
  })

  const onSubmit = async (data: RenewFormData): Promise<void> => {
    try {
      await renewMutation.mutateAsync({
        id: policy.id,
        start_date: data.start_date,
        end_date: data.end_date,
        premium_amount: data.premium_amount ?? null,
      })
      toast.success(t('insurance.renewed'))
      onSuccess()
      onClose()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('insurance.renewAction')))
    }
  }

  return (
    <FormModalWrapper
      title={t('insurance.renewTitle', { provider: policy.provider })}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button
            type="submit"
            form="renew-policy-form"
            variant="primary"
            icon={RefreshCw}
            loading={isSubmitting}
            disabled={isSubmitting}
          >
            {t('insurance.renewConfirm')}
          </Button>
        </>
      }
    >
      <form id="renew-policy-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
        <p className="text-sm text-text-dim">{t('insurance.renewExplain')}</p>
        <Field
          id="renew_premium"
          label={t('insurance.newPremium')}
          hint={t('insurance.newPremiumHint')}
          error={errors.premium_amount}
        >
          <NumberInput
            id="renew_premium"
            {...registerDecimal(register, 'premium_amount')}
            invalid={!!errors.premium_amount}
            disabled={isSubmitting}
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field id="renew_start" label={t('common:startDate')} required error={errors.start_date}>
            <Input
              id="renew_start"
              type="date"
              {...register('start_date')}
              invalid={!!errors.start_date}
              disabled={isSubmitting}
            />
          </Field>
          <Field id="renew_end" label={t('common:endDate')} required error={errors.end_date}>
            <Input
              id="renew_end"
              type="date"
              {...register('end_date')}
              invalid={!!errors.end_date}
              disabled={isSubmitting}
            />
          </Field>
        </div>
      </form>
    </FormModalWrapper>
  )
}
