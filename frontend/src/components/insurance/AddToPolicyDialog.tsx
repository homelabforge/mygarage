/**
 * From a vehicle's tab: put THIS vehicle on a policy the household already
 * has, instead of typing the policy again. Its share grows the policy premium
 * by the same amount, so every other vehicle keeps the share it had.
 */

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from '../FormModalWrapper'
import { Button, Field, NumberInput, Select } from '../ui'
import { POLICY_TYPES } from '../../schemas/insurance'
import { useAttachPolicyVehicle } from '../../hooks/queries/useInsuranceRecords'
import { parseDecimalInput } from '../../utils/decimalInput'
import { getActiveLocale } from '../../constants/i18n'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'
import type { InsurancePolicy, PolicyVehicleCreate } from '../../types/insurance'

interface AddToPolicyDialogProps {
  vin: string
  /** Current policies that do not cover this vehicle yet. */
  policies: InsurancePolicy[]
  onClose: () => void
  onSuccess: () => void
}

export default function AddToPolicyDialog({ vin, policies, onClose, onSuccess }: AddToPolicyDialogProps) {
  const { t } = useTranslation('forms')
  const attachMutation = useAttachPolicyVehicle()
  const [policyId, setPolicyId] = useState(policies.length === 1 ? String(policies[0].id) : '')
  const [policyType, setPolicyType] = useState('')
  const [share, setShare] = useState('')
  const [shareError, setShareError] = useState<string | null>(null)

  const submit = async (): Promise<void> => {
    let premiumShare: number | null = null
    // The same locale-aware reading every other money field uses, so a comma
    // decimal is a number here too (#140).
    const parsed = parseDecimalInput(share, getActiveLocale())
    if (parsed.kind === 'invalid' || (parsed.kind === 'value' && parsed.value < 0)) {
      setShareError(t('common:validation.amount.invalid'))
      return
    }
    if (parsed.kind === 'value') premiumShare = parsed.value
    setShareError(null)
    try {
      await attachMutation.mutateAsync({
        policyId: Number(policyId),
        vin,
        policy_type: policyType as PolicyVehicleCreate['policy_type'],
        premium_share: premiumShare,
      })
      toast.success(t('insurance.vehicleAdded'))
      onSuccess()
      onClose()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('insurance.saveAction')))
    }
  }

  return (
    <FormModalWrapper
      title={t('insurance.addToExistingTitle')}
      onClose={onClose}
      width="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={attachMutation.isPending}>
            {t('common:cancel')}
          </Button>
          <Button
            variant="primary"
            icon={Plus}
            onClick={submit}
            loading={attachMutation.isPending}
            disabled={!policyId || !policyType || attachMutation.isPending}
          >
            {t('common:add')}
          </Button>
        </>
      }
    >
      <div className="p-6 space-y-4">
        <Field id="existing_policy" label={t('insurance.existingPolicy')} required>
          <Select
            id="existing_policy"
            value={policyId}
            onChange={(event) => setPolicyId(event.target.value)}
            placeholder={t('insurance.choosePolicy')}
            options={policies.map((policy) => ({
              value: String(policy.id),
              label: `${policy.provider} #${policy.policy_number}`,
            }))}
          />
        </Field>
        <Field id="attach_type" label={t('insurance.policyType')} required>
          <Select
            id="attach_type"
            value={policyType}
            onChange={(event) => setPolicyType(event.target.value)}
            placeholder={t('common:selectType')}
            options={POLICY_TYPES.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
          />
        </Field>
        <Field
          id="attach_share"
          label={t('insurance.vehicleShare')}
          hint={t('insurance.attachShareHint')}
          error={shareError ? { type: 'validate', message: shareError } : undefined}
        >
          <NumberInput
            id="attach_share"
            value={share}
            onChange={(event) => setShare(event.target.value)}
            invalid={!!shareError}
          />
        </Field>
      </div>
    </FormModalWrapper>
  )
}
