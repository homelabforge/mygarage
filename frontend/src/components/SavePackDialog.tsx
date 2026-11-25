/**
 * Save this vehicle's recurring reminders as a reusable pack (issue #165).
 *
 * The vehicle IS the pack editor: you get one vehicle's schedule right with the
 * tools that already exist, then name it here. So there is no pack-item editor
 * anywhere in the app, by design.
 *
 * What the list shows is the vehicle's maintenance RULES, not its reminders. A
 * rule is what a pack item becomes, and a rule with no pending reminder (a
 * mileage rule on a vehicle with no reading yet) still belongs in a pack.
 *
 * Two kinds of rule cannot go in a pack at all, and they are shown disabled with
 * the reason rather than hidden: the user is better served knowing their winch
 * reminder was left out than wondering where it went. See `utils/packSavability`.
 */

import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PackagePlus } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from './FormModalWrapper'
import { Button, Checkbox, Field, Input, Textarea } from './ui'
import { describeRecurrence } from './RecurrenceFields'
import { useMaintenanceRules, useOverwritePack, useSavePack } from '../hooks/useReminders'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { defaultSelection, repeatedTypes, unsavableReason } from '../utils/packSavability'
import { VEHICLE_TYPES, vehicleTypeOptions } from '../schemas/vehicle'
import type { MaintenanceRuleResponse, ReminderPackSummary, SavePackBody } from '../types/reminder'
import type { VehicleType } from '../types/vehicle'

type VehicleTypeValue = NonNullable<SavePackBody['vehicle_types']>[number]

/** The pack being overwritten, as the pack list already holds it. */
export type ExistingPack = Pick<ReminderPackSummary, 'id' | 'name' | 'description' | 'vehicle_types'>

interface SavePackDialogProps {
  vin: string
  /** Prefills the vehicle-type picker; the source vehicle's own type. */
  vehicleType: VehicleType | null | undefined
  /** Set to overwrite an existing pack instead of creating one. */
  existingPack?: ExistingPack
  onClose: () => void
  onSaved: () => void
}

export default function SavePackDialog({
  vin,
  vehicleType,
  existingPack,
  onClose,
  onSaved,
}: SavePackDialogProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const { data: rules, isLoading } = useMaintenanceRules(vin)
  const saveMutation = useSavePack()
  const overwriteMutation = useOverwritePack()
  const pending = saveMutation.isPending || overwriteMutation.isPending

  // An overwrite replaces the whole pack, so it seeds from what the pack says.
  // Seeding a blank description and this vehicle's type wiped the one and
  // narrowed an all-types pack ([]) to a single type.
  const [name, setName] = useState(existingPack?.name ?? '')
  const [description, setDescription] = useState(existingPack?.description ?? '')
  // Only types the checkboxes know get seeded. A restored backup can carry one
  // this version doesn't, and sending it back 422s the whole edit.
  const [types, setTypes] = useState<VehicleTypeValue[]>(() => {
    if (existingPack) {
      return (existingPack.vehicle_types ?? []).flatMap((stored) =>
        VEHICLE_TYPES.filter((known) => known === stored),
      )
    }
    return vehicleType ? [vehicleType] : []
  })
  const [checked, setChecked] = useState<Set<number> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const active = useMemo(() => (rules ?? []).filter((r) => r.is_active), [rules])
  // Null until the rules land, so the default is computed from real data rather
  // than from an empty list that would leave everything unticked.
  const selection = checked ?? defaultSelection(active)
  const selectedRules = active.filter((r) => selection.has(r.id))
  const conflicts = repeatedTypes(selectedRules)

  const toggle = (id: number) =>
    setChecked(() => {
      const next = new Set<number>(selection)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const toggleType = (value: VehicleTypeValue) =>
    setTypes((prev) => (prev.includes(value) ? prev.filter((v) => v !== value) : [...prev, value]))

  const blocked = selectedRules.some((r) => unsavableReason(r, conflicts) !== null)
  const canSave = name.trim().length > 0 && selection.size > 0 && !blocked

  const handleSave = async () => {
    setError(null)
    const body: SavePackBody = {
      vin,
      name: name.trim(),
      description: description.trim(),
      vehicle_types: types,
      rule_ids: [...selection],
    }
    try {
      if (existingPack) {
        await overwriteMutation.mutateAsync({ packId: existingPack.id, body })
        toast.success(t('savePack.overwritten'))
      } else {
        await saveMutation.mutateAsync(body)
        toast.success(t('savePack.saved'))
      }
      onSaved()
    } catch (err) {
      setError(getActionErrorMessage(err, t('savePack.action')))
    }
  }

  const renderRule = (rule: MaintenanceRuleResponse) => {
    const reason = unsavableReason(rule, conflicts)
    const isChecked = selection.has(rule.id)
    // A conflict only disqualifies a rule while it is ticked; unticking the
    // other one clears it, which is why the reason is recomputed every render.
    const disabled = pending || (reason === 'typeless' && !isChecked)
    const recurrence = describeRecurrence(rule, (km) => u.distance.format(km), t)
    return (
      <li key={rule.id} className="rounded-lg border border-border bg-surface-2 px-3 py-2">
        <Checkbox
          id={`save-pack-rule-${rule.id}`}
          label={rule.title}
          checked={isChecked}
          disabled={disabled}
          onChange={() => toggle(rule.id)}
        />
        {recurrence && <p className="text-xs text-text-mute pl-6">{recurrence}</p>}
        {reason && isChecked && (
          <p className="text-xs text-warning pl-6">
            {t('savePack.cannotInclude', {
              reason:
                reason === 'typeless'
                  ? t('savePack.reasonTypeless')
                  : t('savePack.reasonRepeatedType'),
            })}
          </p>
        )}
      </li>
    )
  }

  return (
    <FormModalWrapper
      title={existingPack ? t('savePack.overwriteTitle') : t('savePack.title')}
      icon={PackagePlus}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={pending}>
            {t('common:cancel')}
          </Button>
          <Button onClick={() => void handleSave()} loading={pending} disabled={pending || !canSave}>
            {t('savePack.action')}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <p className="text-sm text-text-mute">{t('savePack.intro')}</p>
        {error && (
          <p
            role="alert"
            className="text-sm text-danger bg-danger/10 border border-danger rounded-lg p-3"
          >
            {error}
          </p>
        )}
        <Field id="save-pack-name" label={t('savePack.name')}>
          <Input
            id="save-pack-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t('savePack.namePlaceholder')}
            disabled={pending}
          />
        </Field>
        <Field id="save-pack-description" label={t('savePack.description')}>
          <Textarea
            id="save-pack-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('savePack.descriptionPlaceholder')}
            rows={2}
            disabled={pending}
          />
        </Field>
        <fieldset>
          <legend className="text-xs font-semibold uppercase tracking-wide text-text-mute mb-2">
            {t('savePack.vehicleTypes')}
          </legend>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1">
            {vehicleTypeOptions(t).map((option) => (
              <Checkbox
                key={option.value}
                id={`save-pack-type-${option.value}`}
                label={option.label}
                checked={types.includes(option.value)}
                disabled={pending}
                onChange={() => toggleType(option.value)}
              />
            ))}
          </div>
          <p className="text-xs text-text-mute mt-1">{t('savePack.vehicleTypesHint')}</p>
        </fieldset>
        <fieldset>
          <legend className="text-xs font-semibold uppercase tracking-wide text-text-mute mb-2">
            {t('savePack.include')}
          </legend>
          {isLoading ? (
            <p className="text-sm text-text-mute">{t('applyPack.loading')}</p>
          ) : active.length === 0 ? (
            <p className="text-sm text-text-mute">{t('savePack.noRules')}</p>
          ) : (
            <ul className="space-y-1">{active.map(renderRule)}</ul>
          )}
          {active.length > 0 && selection.size === 0 && (
            <p className="text-xs text-warning mt-1">{t('savePack.nothingChecked')}</p>
          )}
        </fieldset>
      </div>
    </FormModalWrapper>
  )
}
