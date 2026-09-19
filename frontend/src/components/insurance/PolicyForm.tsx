import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { useFieldArray, useForm, useWatch, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save, FileUp, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from '../FormModalWrapper'
import {
  Button,
  Field,
  IconButton,
  Input,
  NumberInput,
  Select,
  Textarea,
  registerDecimal,
} from '../ui'
import type {
  InsurancePDFParseResponse,
  InsurancePolicy,
  InsurancePolicyCreate,
  NamedField,
  PolicyVehicleCreate,
} from '../../types/insurance'
import {
  makeInsuranceSchema,
  type InsuranceFormData,
  type PolicyVehicleFormData,
  POLICY_TYPES,
  PREMIUM_FREQUENCIES,
  SUGGESTED_POLICY_FIELDS,
  SUGGESTED_VEHICLE_FIELDS,
} from '../../schemas/insurance'
import InsurancePDFUpload from '../InsurancePDFUpload'
import NamedFieldsEditor from './NamedFieldsEditor'
import {
  useCreateInsurancePolicy,
  useReplaceInsurancePolicy,
  useUpdateInsurancePolicy,
} from '../../hooks/queries/useInsuranceRecords'
import { useQuickEntryVehicles } from '../../hooks/queries/useQuickEntryVehicles'
import { vehicleLabel } from '../../utils/vehicleLabel'
import { formatDateForInput } from '../../utils/dateUtils'
import { formatCurrency } from '../../utils/formatUtils'
import { useCurrencyPreference } from '../../hooks/useCurrencyPreference'
import { applyServerErrors } from '../../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'

export type PolicyFormMode = 'create' | 'edit' | 'replace'

interface PolicyFormProps {
  mode: PolicyFormMode
  /** edit: the policy being edited. replace: the policy being replaced. */
  policy?: InsurancePolicy
  /** create from a vehicle's tab: that vehicle starts attached. */
  initialVin?: string
  onClose: () => void
  onSuccess: () => void
}

const POLICY_TYPE_VALUES: readonly string[] = POLICY_TYPES.map((option) => option.value)

function emptyVehicle(vin: string, over: Partial<PolicyVehicleFormData> = {}): PolicyVehicleFormData {
  return {
    vin,
    policy_type: '',
    premium_share: undefined,
    deductible: undefined,
    coverage_limits: '',
    notes: '',
    effective_to: '',
    fields: [],
    ...over,
  }
}

const cleanFields = (fields: NamedField[]): NamedField[] =>
  fields.map((field) => ({ label: field.label.trim(), value: field.value.trim() }))

export default function PolicyForm({ mode, policy, initialVin, onClose, onSuccess }: PolicyFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = mode === 'edit'
  const isReplace = mode === 'replace'
  const createMutation = useCreateInsurancePolicy()
  const updateMutation = useUpdateInsurancePolicy()
  const replaceMutation = useReplaceInsurancePolicy()
  const { data: garage = [] } = useQuickEntryVehicles()
  const { currencyCode, locale } = useCurrencyPreference()
  const [showPDFUpload, setShowPDFUpload] = useState(false)
  const [pickedVin, setPickedVin] = useState('')
  const [endOldOn, setEndOldOn] = useState('')

  // A creator can hold a policy that covers vehicles they can no longer see.
  // Sending a vehicle list would then REMOVE the hidden ones (on edit) or leave
  // them off the new policy (on a switch), so the vehicle editor is locked and
  // no vehicle list is sent at all: the backend then keeps or carries them all.
  //
  // A switch is stricter still: it CREATES links, which takes write access to
  // every vehicle, so one the user can only read would 403 the whole switch.
  // Carrying everything over by type needs no such access, so that is what a
  // locked switch does.
  const vehiclesLocked =
    ((isEdit || isReplace) && (policy?.other_vehicle_count ?? 0) > 0) ||
    (isReplace && (policy?.vehicles ?? []).some((vehicle) => !vehicle.can_edit))
  // Vehicles the user can see but not write: shown, never editable here.
  const readOnlyVins = useMemo(
    () =>
      new Set(
        isEdit ? (policy?.vehicles ?? []).filter((v) => !v.can_edit).map((v) => v.vin) : []
      ),
    [isEdit, policy]
  )

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it, so a rebuild can't
  // discard what the user typed.
  const schema = useMemo(() => makeInsuranceSchema(t), [t])

  const startingVehicles: PolicyVehicleFormData[] = useMemo(() => {
    if (isEdit && policy) {
      return (policy.vehicles ?? []).map((vehicle) =>
        emptyVehicle(vehicle.vin, {
          policy_type: vehicle.policy_type,
          premium_share: vehicle.premium_share != null ? Number(vehicle.premium_share) : undefined,
          deductible: vehicle.deductible != null ? Number(vehicle.deductible) : undefined,
          coverage_limits: vehicle.coverage_limits ?? '',
          notes: vehicle.notes ?? '',
          effective_to: vehicle.effective_to ?? '',
          fields: (vehicle.fields ?? []).map((field) => ({ ...field })),
        })
      )
    }
    if (isReplace && policy) {
      // A new insurer's coverages differ: carry the vehicles, not their terms.
      return (policy.vehicles ?? [])
        .filter((vehicle) => !vehicle.effective_to)
        .map((vehicle) => emptyVehicle(vehicle.vin, { policy_type: vehicle.policy_type }))
    }
    return initialVin ? [emptyVehicle(initialVin)] : []
  }, [isEdit, isReplace, policy, initialVin])

  const {
    register,
    control,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    setError: setFieldError,
  } = useForm<InsuranceFormData>({
    resolver: zodResolver(schema) as Resolver<InsuranceFormData>,
    defaultValues: {
      provider: isEdit ? (policy?.provider ?? '') : '',
      policy_number: isEdit ? (policy?.policy_number ?? '') : '',
      start_date: isEdit
        ? formatDateForInput(policy?.start_date)
        : isReplace
          ? formatDateForInput(policy?.end_date)
          : '',
      end_date: isEdit ? formatDateForInput(policy?.end_date) : '',
      premium_amount:
        isEdit && policy?.premium_amount != null ? Number(policy.premium_amount) : undefined,
      premium_frequency: (isEdit || isReplace ? policy?.premium_frequency : undefined) ?? undefined,
      notes: isEdit ? (policy?.notes ?? '') : '',
      fields: isEdit && policy ? (policy.fields ?? []).map((field) => ({ ...field })) : [],
      vehicles: startingVehicles,
    },
  })

  const { fields: vehicleRows, append, remove, update } = useFieldArray({
    control,
    name: 'vehicles',
  })
  const watchedVehicles = useWatch({ control, name: 'vehicles' })
  const watchedPremium = useWatch({ control, name: 'premium_amount' })

  const nameByVin = useMemo(() => {
    const names = new Map<string, string>()
    for (const vehicle of garage) names.set(vehicle.vin, vehicleLabel(vehicle))
    for (const vehicle of policy?.vehicles ?? []) {
      if (!names.has(vehicle.vin)) names.set(vehicle.vin, vehicle.vehicle_name)
    }
    return names
  }, [garage, policy])

  const attached = new Set(vehicleRows.map((row) => row.vin))
  const pickable = garage.filter((vehicle) => !attached.has(vehicle.vin))

  // What an untouched share input will resolve to, mirrored from the backend's
  // rule so the placeholder tells the truth: the premium, less every explicit
  // share, split evenly across the vehicles with no share of their own.
  const premium = typeof watchedPremium === 'number' ? watchedPremium : Number(watchedPremium)
  const explicit = (watchedVehicles ?? []).map((vehicle) => {
    const share = vehicle?.premium_share as unknown
    if (share === undefined || share === null || share === '') return null
    const parsed = typeof share === 'number' ? share : Number(String(share).replace(',', '.'))
    return Number.isFinite(parsed) ? parsed : null
  })
  const allocated = explicit.reduce<number>((sum, share) => sum + (share ?? 0), 0)
  const unsetCount = explicit.filter((share) => share === null).length
  const hasPremium = Number.isFinite(premium) && watchedPremium !== undefined && watchedPremium !== null
  const remainderCents = Math.round(Math.max(premium - allocated, 0) * 100)
  const evenSplit =
    hasPremium && unsetCount > 0 ? Math.floor(remainderCents / unsetCount) / 100 : null
  const splitIsExact = unsetCount > 0 && remainderCents % unsetCount === 0
  const overAllocated = hasPremium && allocated > premium + 0.004
  const underAllocated =
    hasPremium && unsetCount === 0 && explicit.length > 0 && Math.abs(allocated - premium) > 0.004
  const money = (value: number): string => formatCurrency(value, { currencyCode, locale })

  const addVehicle = () => {
    if (!pickedVin) return
    append(emptyVehicle(pickedVin))
    setPickedVin('')
  }

  const handlePDFDataExtracted = (parsed: InsurancePDFParseResponse) => {
    const data = parsed.data
    if (data.provider) setValue('provider', data.provider)
    if (data.policy_number) setValue('policy_number', data.policy_number)
    if (data.start_date) setValue('start_date', data.start_date)
    if (data.end_date) setValue('end_date', data.end_date)
    if (data.premium_amount) setValue('premium_amount', Number(data.premium_amount))
    if (data.premium_frequency) setValue('premium_frequency', data.premium_frequency)
    if (data.notes) setValue('notes', data.notes)

    const parsedType =
      data.policy_type && POLICY_TYPE_VALUES.includes(data.policy_type) ? data.policy_type : ''
    for (const vehicle of parsed.vehicles) {
      if (!vehicle.matched) continue
      const parsedRow = emptyVehicle(vehicle.vin, {
        policy_type: parsedType,
        premium_share: vehicle.premium_share ? Number(vehicle.premium_share) : undefined,
        deductible: vehicle.deductible ? Number(vehicle.deductible) : undefined,
        coverage_limits: data.coverage_limits ?? '',
      })
      // The vehicle whose tab opened the form is attached already: it takes
      // the document's figures rather than being skipped for being there.
      const at = vehicleRows.findIndex((row) => row.vin === vehicle.vin)
      if (at === -1) append(parsedRow)
      else update(at, parsedRow)
    }
  }

  const onSubmit = async (data: InsuranceFormData) => {
    try {
      // null, never '', for a cleared optional: every field here is mounted,
      // so an explicit null correctly clears the column (#140).
      const vehicles = data.vehicles.map((vehicle) => ({
        vin: vehicle.vin,
        policy_type: vehicle.policy_type as PolicyVehicleCreate['policy_type'],
        premium_share: vehicle.premium_share ?? null,
        deductible: vehicle.deductible ?? null,
        coverage_limits: vehicle.coverage_limits || null,
        notes: vehicle.notes || null,
        effective_to: vehicle.effective_to || null,
        fields: cleanFields(vehicle.fields),
      }))
      const base = {
        provider: data.provider,
        policy_number: data.policy_number,
        start_date: data.start_date,
        end_date: data.end_date,
        premium_amount: data.premium_amount ?? null,
        premium_frequency: (data.premium_frequency ||
          null) as InsurancePolicyCreate['premium_frequency'],
        notes: data.notes || null,
      }

      // Create-shaped rows: a vehicle joins a NEW policy for its whole term.
      const joining = vehicles.map(({ effective_to: _unused, ...vehicle }) => vehicle)

      if (isReplace && policy) {
        await replaceMutation.mutateAsync({
          id: policy.id,
          ...base,
          // The new insurer's coverages go in with the switch. With hidden
          // vehicles nothing is sent, so the backend carries every vehicle.
          ...(vehiclesLocked ? {} : { vehicles: joining }),
          end_old_on: endOldOn || null,
        })
      } else if (isEdit && policy) {
        // With the vehicle list locked the shares cannot be resent, so a
        // premium change must say what happens to them, or a policy whose
        // shares are all fixed could never have its premium corrected.
        const premiumChanged =
          (data.premium_amount ?? null) !==
          (policy.premium_amount != null ? Number(policy.premium_amount) : null)
        await updateMutation.mutateAsync({
          id: policy.id,
          ...base,
          fields: cleanFields(data.fields),
          ...(vehiclesLocked
            ? premiumChanged
              ? { share_strategy: 'rescale' as const }
              : {}
            : { vehicles }),
        })
      } else {
        await createMutation.mutateAsync({
          ...base,
          fields: cleanFields(data.fields),
          vehicles: joining,
        })
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500,
      // or the allocation rule's plain-text 422): it carries no field
      // problems, so `unhandled` alone would stay empty and nothing would show.
      const { attached: shown, unhandled } = applyServerErrors<InsuranceFormData>(
        setFieldError,
        err,
        ['provider', 'policy_number', 'start_date', 'end_date', 'premium_amount', 'premium_frequency', 'notes']
      )
      if (shown.length === 0 || unhandled.length > 0) {
        toast.error(getActionErrorMessage(err, t('insurance.saveAction')))
      }
    }
  }

  const title = isReplace
    ? t('insurance.switchTitle')
    : isEdit
      ? t('insurance.editTitle')
      : t('insurance.createTitle')

  return (
    <>
      <FormModalWrapper
        title={title}
        onClose={onClose}
        width="lg"
        footer={
          <>
            <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
              {t('common:cancel')}
            </Button>
            <Button
              type="submit"
              form="insurance-form"
              variant="primary"
              icon={Save}
              loading={isSubmitting}
              disabled={isSubmitting}
            >
              {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
            </Button>
          </>
        }
      >
        <form id="insurance-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-5">
          {mode === 'create' && (
            <div>
              <Button
                type="button"
                variant="secondary"
                icon={FileUp}
                onClick={() => setShowPDFUpload(true)}
                className="w-full"
              >
                {t('insuranceForm.importFromPdf')}
              </Button>
              <p className="text-xs text-text-mute mt-2 text-center">{t('insurance.pdfUploadHint')}</p>
            </div>
          )}
          {isReplace && policy && (
            <p className="text-sm text-text-dim">
              {t('insurance.switchExplain', { provider: policy.provider })}
            </p>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="provider" label={t('insurance.provider')} required error={errors.provider}>
              <Input
                id="provider"
                type="text"
                {...register('provider')}
                placeholder={t('insuranceForm.providerPlaceholder')}
                invalid={!!errors.provider}
                disabled={isSubmitting}
              />
            </Field>
            <Field
              id="policy_number"
              label={t('insurance.policyNumber')}
              required
              error={errors.policy_number}
            >
              <Input
                id="policy_number"
                type="text"
                {...register('policy_number')}
                placeholder={t('insuranceForm.policyNumberPlaceholder')}
                invalid={!!errors.policy_number}
                disabled={isSubmitting}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field id="start_date" label={t('common:startDate')} required error={errors.start_date}>
              <Input
                id="start_date"
                type="date"
                {...register('start_date')}
                invalid={!!errors.start_date}
                disabled={isSubmitting}
              />
            </Field>
            <Field id="end_date" label={t('common:endDate')} required error={errors.end_date}>
              <Input
                id="end_date"
                type="date"
                {...register('end_date')}
                invalid={!!errors.end_date}
                disabled={isSubmitting}
              />
            </Field>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <Field
              id="premium_amount"
              label={t('insurance.policyPremium')}
              hint={t('insurance.policyPremiumHint')}
              error={errors.premium_amount}
            >
              <NumberInput
                id="premium_amount"
                {...registerDecimal(register, 'premium_amount')}
                placeholder={t('insuranceForm.premiumAmountPlaceholder')}
                invalid={!!errors.premium_amount}
                disabled={isSubmitting}
              />
            </Field>
            <Field
              id="premium_frequency"
              label={t('insurance.premiumFrequency')}
              error={errors.premium_frequency}
            >
              <Select
                id="premium_frequency"
                {...register('premium_frequency')}
                disabled={isSubmitting}
                placeholder={t('insurance.selectFrequency')}
                options={PREMIUM_FREQUENCIES.map((option) => ({
                  value: option.value,
                  label: t(option.labelKey),
                }))}
              />
            </Field>
          </div>

          {isReplace && (
            <Field id="end_old_on" label={t('insurance.endOldOn')} hint={t('insurance.endOldOnHint')}>
              <Input
                id="end_old_on"
                type="date"
                value={endOldOn}
                onChange={(event) => setEndOldOn(event.target.value)}
                disabled={isSubmitting}
              />
            </Field>
          )}

          {!isReplace && (
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium text-text">{t('insurance.policyDetails')}</legend>
              <NamedFieldsEditor
                control={control}
                register={register}
                name="fields"
                suggestions={SUGGESTED_POLICY_FIELDS}
                disabled={isSubmitting}
                idPrefix="policy-field"
                errors={errors.fields}
              />
            </fieldset>
          )}

          <fieldset className="space-y-3">
            <legend className="text-sm font-medium text-text">{t('insurance.coveredVehicles')}</legend>

            {vehiclesLocked ? (
              <p className="text-sm text-text-mute">{t('insurance.vehiclesLocked')}</p>
            ) : (
              <>
                {vehicleRows.length === 0 && (
                  <p className="text-sm text-text-mute">{t('insurance.noVehiclesYet')}</p>
                )}
                {vehicleRows.map((row, index) => {
                  const rowErrors = errors.vehicles?.[index]
                  // Visible but not writable: shown for context, never editable.
                  const rowLocked = readOnlyVins.has(row.vin)
                  const rowDisabled = isSubmitting || rowLocked
                  return (
                    <div
                      key={row.id}
                      className="rounded-lg border border-border-soft bg-surface-2 p-4 space-y-3"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-text">
                          {nameByVin.get(row.vin) ?? row.vin}
                        </span>
                        {rowLocked ? (
                          <span className="text-xs text-text-mute">{t('insurance.vehicleReadOnly')}</span>
                        ) : (
                          <IconButton
                            icon={Trash2}
                            label={t('insurance.removeVehicle')}
                            variant="ghost"
                            size="sm"
                            disabled={rowDisabled}
                            onClick={() => remove(index)}
                          />
                        )}
                      </div>
                      <div className="grid gap-4 grid-cols-3">
                        <Field
                          id={`vehicle-${index}-type`}
                          label={t('insurance.policyType')}
                          required
                          error={rowErrors?.policy_type}
                        >
                          <Select
                            id={`vehicle-${index}-type`}
                            {...register(`vehicles.${index}.policy_type`)}
                            disabled={rowDisabled}
                            invalid={!!rowErrors?.policy_type}
                            placeholder={t('common:selectType')}
                            options={POLICY_TYPES.map((option) => ({
                              value: option.value,
                              label: t(option.labelKey),
                            }))}
                          />
                        </Field>
                            <Field
                              id={`vehicle-${index}-share`}
                              label={t('insurance.vehicleShare')}
                              error={rowErrors?.premium_share}
                            >
                              <NumberInput
                                id={`vehicle-${index}-share`}
                                {...registerDecimal(register, `vehicles.${index}.premium_share`)}
                                placeholder={
                                  evenSplit == null
                                    ? t('insurance.evenSplitUnknown')
                                    : splitIsExact
                                      ? t('insurance.evenSplit', { amount: money(evenSplit) })
                                      : t('insurance.evenSplitAbout', { amount: money(evenSplit) })
                                }
                                invalid={!!rowErrors?.premium_share}
                                disabled={rowDisabled}
                              />
                            </Field>
                            <Field
                              id={`vehicle-${index}-deductible`}
                              label={t('insurance.deductible')}
                              error={rowErrors?.deductible}
                            >
                              <NumberInput
                                id={`vehicle-${index}-deductible`}
                                {...registerDecimal(register, `vehicles.${index}.deductible`)}
                                placeholder={t('insuranceForm.deductiblePlaceholder')}
                                invalid={!!rowErrors?.deductible}
                                disabled={rowDisabled}
                              />
                            </Field>
                      </div>
                          <Field
                            id={`vehicle-${index}-coverage`}
                            label={t('insurance.coverageLimits')}
                          >
                            <Textarea
                              id={`vehicle-${index}-coverage`}
                              rows={2}
                              {...register(`vehicles.${index}.coverage_limits`)}
                              placeholder={t('insuranceForm.coverageLimitsPlaceholder')}
                              disabled={rowDisabled}
                            />
                          </Field>
                          <NamedFieldsEditor
                            control={control}
                            register={register}
                            name={`vehicles.${index}.fields`}
                            suggestions={SUGGESTED_VEHICLE_FIELDS}
                            disabled={rowDisabled}
                            idPrefix={`vehicle-${index}-field`}
                            errors={rowErrors?.fields}
                          />
                          {isEdit && (
                            <Field
                              id={`vehicle-${index}-effective-to`}
                              label={t('insurance.removedOn')}
                              hint={t('insurance.removedOnHint')}
                            >
                              <Input
                                id={`vehicle-${index}-effective-to`}
                                type="date"
                                {...register(`vehicles.${index}.effective_to`)}
                                disabled={rowDisabled}
                              />
                            </Field>
                          )}
                    </div>
                  )
                })}

                {hasPremium && vehicleRows.length > 0 && (
                  <p
                    role={overAllocated || underAllocated ? 'alert' : undefined}
                    className={`text-sm ${
                      overAllocated || underAllocated ? 'text-danger' : 'text-text-mute'
                    }`}
                  >
                    {overAllocated
                      ? t('insurance.overAllocated', {
                          allocated: money(allocated),
                          premium: money(premium),
                        })
                      : underAllocated
                        ? t('insurance.underAllocated', {
                            allocated: money(allocated),
                            premium: money(premium),
                          })
                        : t('insurance.allocated', {
                            allocated: money(allocated),
                            premium: money(premium),
                          })}
                  </p>
                )}

                {pickable.length > 0 && (
                  <div className="flex gap-2 items-end">
                    <div className="flex-1">
                    <Field id="add-vehicle" label={t('insurance.addVehicle')}>
                      <Select
                        id="add-vehicle"
                        value={pickedVin}
                        onChange={(event) => setPickedVin(event.target.value)}
                        disabled={isSubmitting}
                        placeholder={t('insurance.chooseVehicle')}
                        options={pickable.map((vehicle) => ({
                          value: vehicle.vin,
                          label: vehicleLabel(vehicle),
                        }))}
                      />
                    </Field>
                    </div>
                    <Button
                      type="button"
                      variant="secondary"
                      icon={Plus}
                      onClick={addVehicle}
                      disabled={!pickedVin || isSubmitting}
                    >
                      {t('common:add')}
                    </Button>
                  </div>
                )}
              </>
            )}
          </fieldset>

          <Field id="notes" label={t('common:notes')}>
            <Textarea
              id="notes"
              rows={2}
              {...register('notes')}
              placeholder={t('common:additionalNotes')}
              disabled={isSubmitting}
            />
          </Field>
        </form>
      </FormModalWrapper>

      {showPDFUpload && (
        <InsurancePDFUpload
          onDataExtracted={handlePDFDataExtracted}
          onClose={() => setShowPDFUpload(false)}
        />
      )}
    </>
  )
}
