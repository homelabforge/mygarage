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
import { Button, Field, Input, NumberInput, Select } from '../ui'
import { NO_CLAIMS_CLASS_PATTERN, policyTypeOptions } from '../../schemas/insurance'
import { useInsuranceProfile } from '../../hooks/useInsuranceProfile'
import { moneyTextError } from '../../schemas/shared'
import { useAttachPolicyVehicle } from '../../hooks/queries/useInsuranceRecords'
import { parseOptionalDecimal } from '../../utils/decimalInput'
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
  const [noClaims, setNoClaims] = useState('')
  // #211 — the country's formulas first; its no-claims scheme names the field.
  const insuranceProfile = useInsuranceProfile()
  const typeOptions = policyTypeOptions(t, insuranceProfile.policyTypes)
  const noClaimsInvalid = !!noClaims.trim() && !NO_CLAIMS_CLASS_PATTERN.test(noClaims.trim())

  const submit = async (): Promise<void> => {
    // The same locale-aware reading every other money field uses, so a comma
    // decimal is a number here too (#140), and the API's money bounds.
    const problem = moneyTextError(t, share)
    if (problem) {
      setShareError(problem)
      return
    }
    const premiumShare = parseOptionalDecimal(share) ?? null
    setShareError(null)
    try {
      await attachMutation.mutateAsync({
        policyId: Number(policyId),
        vin,
        policy_type: policyType as PolicyVehicleCreate['policy_type'],
        premium_share: premiumShare,
        no_claims_class: noClaims.trim() || null,
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
            disabled={!policyId || !policyType || noClaimsInvalid || attachMutation.isPending}
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
            options={typeOptions}
          />
        </Field>
        {insuranceProfile.noClaims && (
          <Field
            id="attach_no_claims"
            label={insuranceProfile.noClaims.name}
            hint={t('insurance.noClaimsHint')}
            error={
              noClaimsInvalid
                ? { type: 'validate', message: t('insurance.noClaimsClassInvalid') }
                : undefined
            }
          >
            <Input
              id="attach_no_claims"
              type="text"
              maxLength={10}
              value={noClaims}
              placeholder={insuranceProfile.noClaims.example}
              onChange={(event) => setNoClaims(event.target.value)}
              invalid={noClaimsInvalid}
            />
          </Field>
        )}
        <Field
          id="attach_share"
          label={t('insurance.vehicleShare')}
          hint={t('insurance.attachShareHint')}
          error={shareError ? { type: 'validate', message: shareError } : undefined}
        >
          <NumberInput
            id="attach_share"
            value={share}
            onChange={(event) => {
              setShare(event.target.value)
              setShareError(null)
            }}
            invalid={!!shareError}
          />
        </Field>
      </div>
    </FormModalWrapper>
  )
}
