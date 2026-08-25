import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Droplets, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardHeader, Button, Field, Input, NumberInput, Textarea, Mono } from '../ui'
import FormModalWrapper from '../FormModalWrapper'
import CardEditOverlay, { EDITABLE_CARD_CLASS } from './CardEditOverlay'
import vehicleService from '../../services/vehicleService'
import { emptyToNull, str } from '../../utils/formUtils'
import { toCanonicalLiters } from '../../utils/decimalSafe'
import { parseDecimalInput } from '../../utils/decimalInput'
import { getActiveLocale } from '@/constants/i18n'
import { UnitConverter, UnitFormatter } from '../../utils/units'
import { useUnitPreference } from '../../hooks/useUnitPreference'
import type { Vehicle, VehicleUpdate } from '../../types/vehicle'

interface VehicleSpecsPanelProps {
  vin: string
  vehicle: Vehicle
  onUpdated: (vehicle: Vehicle) => void
  /** When this counter increments, open the editor (used by Ask My Garage). */
  editRequestKey?: number
}

type SpecForm = {
  oil_viscosity: string
  oil_capacity: string
  oil_filter_part_number: string
  lug_nut_torque: string
  coolant_type: string
  brake_fluid_type: string
  transmission_fluid_type: string
  maintenance_specs_notes: string
}

function seedForm(vehicle: Vehicle, system: 'metric' | 'imperial'): SpecForm {
  const oilLiters =
    vehicle.oil_capacity_liters != null ? Number(vehicle.oil_capacity_liters) : null
  const torqueNm =
    vehicle.lug_nut_torque_nm != null ? Number(vehicle.lug_nut_torque_nm) : null

  const oilDisplay =
    oilLiters == null || Number.isNaN(oilLiters)
      ? ''
      : system === 'imperial'
        ? String(UnitConverter.litersToGallons(oilLiters) ?? oilLiters)
        : String(oilLiters)

  const torqueDisplay =
    torqueNm == null || Number.isNaN(torqueNm)
      ? ''
      : system === 'imperial'
        ? String(UnitConverter.nmToLbft(torqueNm) ?? torqueNm)
        : String(torqueNm)

  return {
    oil_viscosity: str(vehicle.oil_viscosity),
    oil_capacity: oilDisplay,
    oil_filter_part_number: str(vehicle.oil_filter_part_number),
    lug_nut_torque: torqueDisplay,
    coolant_type: str(vehicle.coolant_type),
    brake_fluid_type: str(vehicle.brake_fluid_type),
    transmission_fluid_type: str(vehicle.transmission_fluid_type),
    maintenance_specs_notes: str(vehicle.maintenance_specs_notes),
  }
}

/**
 * Overview card for structured maintenance specs (oil, lug torque, fluids).
 * Canonical storage is liters / Nm; the editor converts for imperial users.
 */
export default function VehicleSpecsPanel({
  vin,
  vehicle,
  onUpdated,
  editRequestKey = 0,
}: VehicleSpecsPanelProps) {
  const { t } = useTranslation('vehicles')
  const { system } = useUnitPreference()
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<SpecForm>(() => seedForm(vehicle, system))

  useEffect(() => {
    if (open) setForm(seedForm(vehicle, system))
  }, [open, vehicle, system])

  useEffect(() => {
    if (editRequestKey > 0) setOpen(true)
  }, [editRequestKey])

  const hasSpecs = Boolean(
    vehicle.oil_viscosity ||
      vehicle.oil_capacity_liters != null ||
      vehicle.oil_filter_part_number ||
      vehicle.lug_nut_torque_nm != null ||
      vehicle.coolant_type ||
      vehicle.brake_fluid_type ||
      vehicle.transmission_fluid_type ||
      vehicle.maintenance_specs_notes,
  )

  const setField = (key: keyof SpecForm, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const locale = getActiveLocale()
      let oil_capacity_liters: number | null = null
      if (form.oil_capacity.trim()) {
        const parsed = parseDecimalInput(form.oil_capacity, locale)
        if (parsed.kind === 'invalid') {
          toast.error(t('detail.specs.oilCapacityInvalid'))
          setSaving(false)
          return
        }
        if (parsed.kind === 'value') {
          oil_capacity_liters = toCanonicalLiters(parsed.value, system)
        }
      }

      let lug_nut_torque_nm: number | null = null
      if (form.lug_nut_torque.trim()) {
        const parsed = parseDecimalInput(form.lug_nut_torque, locale)
        if (parsed.kind === 'invalid') {
          toast.error(t('detail.specs.lugTorqueInvalid'))
          setSaving(false)
          return
        }
        if (parsed.kind === 'value') {
          lug_nut_torque_nm =
            system === 'imperial'
              ? UnitConverter.lbftToNm(parsed.value)
              : parsed.value
        }
      }

      const payload: VehicleUpdate = {
        oil_viscosity: emptyToNull(form.oil_viscosity),
        oil_capacity_liters,
        oil_filter_part_number: emptyToNull(form.oil_filter_part_number),
        lug_nut_torque_nm,
        coolant_type: emptyToNull(form.coolant_type),
        brake_fluid_type: emptyToNull(form.brake_fluid_type),
        transmission_fluid_type: emptyToNull(form.transmission_fluid_type),
        maintenance_specs_notes: emptyToNull(form.maintenance_specs_notes),
      }

      const updated = await vehicleService.update(vin, payload)
      onUpdated(updated)
      setOpen(false)
      toast.success(t('detail.specs.saveSuccess'))
    } catch {
      toast.error(t('detail.specs.saveError'))
    } finally {
      setSaving(false)
    }
  }

  const volumeUnit = system === 'imperial' ? 'gal' : 'L'
  const torqueUnit = UnitFormatter.getTorqueUnit(system)

  return (
    <>
      <Card breakInside className={EDITABLE_CARD_CLASS}>
        <CardEditOverlay
          label={t('detail.specs.editAria')}
          onClick={() => setOpen(true)}
        />
        <CardHeader title={t('detail.specs.title')} />
        {hasSpecs ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {vehicle.oil_viscosity && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.oilViscosity')}</p>
                <Mono size="sm" className="block">{vehicle.oil_viscosity}</Mono>
              </div>
            )}
            {vehicle.oil_capacity_liters != null && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.oilCapacity')}</p>
                <Mono size="sm" className="block">
                  {UnitFormatter.formatVolume(Number(vehicle.oil_capacity_liters), system)}
                </Mono>
              </div>
            )}
            {vehicle.oil_filter_part_number && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.oilFilter')}</p>
                <Mono size="sm" className="block">{vehicle.oil_filter_part_number}</Mono>
              </div>
            )}
            {vehicle.lug_nut_torque_nm != null && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.lugTorque')}</p>
                <Mono size="sm" className="block">
                  {UnitFormatter.formatTorque(Number(vehicle.lug_nut_torque_nm), system, true)}
                </Mono>
              </div>
            )}
            {vehicle.coolant_type && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.coolant')}</p>
                <p className="font-medium text-text">{vehicle.coolant_type}</p>
              </div>
            )}
            {vehicle.brake_fluid_type && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.brakeFluid')}</p>
                <p className="font-medium text-text">{vehicle.brake_fluid_type}</p>
              </div>
            )}
            {vehicle.transmission_fluid_type && (
              <div>
                <p className="text-sm text-text-mute">{t('detail.specs.transFluid')}</p>
                <p className="font-medium text-text">{vehicle.transmission_fluid_type}</p>
              </div>
            )}
            {vehicle.maintenance_specs_notes && (
              <div className="sm:col-span-2">
                <p className="text-sm text-text-mute">{t('detail.specs.notes')}</p>
                <p className="text-sm text-text whitespace-pre-wrap">{vehicle.maintenance_specs_notes}</p>
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-text-mute">{t('detail.specs.empty')}</p>
        )}
      </Card>

      <FormModalWrapper
        title={t('detail.specs.title')}
        icon={Droplets}
        onClose={() => setOpen(false)}
        isOpen={open}
        width="md"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={saving}>
              {t('common:cancel')}
            </Button>
            <Button variant="primary" onClick={handleSave} loading={saving}>
              {t('common:save')}
            </Button>
          </div>
        }
      >
        <div className="space-y-4">
          <Field id="spec_oil_viscosity" label={t('detail.specs.oilViscosity')}>
            <Input
              id="spec_oil_viscosity"
              value={form.oil_viscosity}
              onChange={(e) => setField('oil_viscosity', e.target.value)}
              placeholder="5W-30"
            />
          </Field>
          <Field id="spec_oil_capacity" label={`${t('detail.specs.oilCapacity')} (${volumeUnit})`}>
            <NumberInput
              id="spec_oil_capacity"
              value={form.oil_capacity}
              onChange={(e) => setField('oil_capacity', e.target.value)}
            />
          </Field>
          <Field id="spec_oil_filter" label={t('detail.specs.oilFilter')}>
            <Input
              id="spec_oil_filter"
              value={form.oil_filter_part_number}
              onChange={(e) => setField('oil_filter_part_number', e.target.value)}
            />
          </Field>
          <Field id="spec_lug_torque" label={`${t('detail.specs.lugTorque')} (${torqueUnit})`}>
            <NumberInput
              id="spec_lug_torque"
              value={form.lug_nut_torque}
              onChange={(e) => setField('lug_nut_torque', e.target.value)}
            />
          </Field>
          <Field id="spec_coolant" label={t('detail.specs.coolant')}>
            <Input
              id="spec_coolant"
              value={form.coolant_type}
              onChange={(e) => setField('coolant_type', e.target.value)}
            />
          </Field>
          <Field id="spec_brake_fluid" label={t('detail.specs.brakeFluid')}>
            <Input
              id="spec_brake_fluid"
              value={form.brake_fluid_type}
              onChange={(e) => setField('brake_fluid_type', e.target.value)}
            />
          </Field>
          <Field id="spec_trans_fluid" label={t('detail.specs.transFluid')}>
            <Input
              id="spec_trans_fluid"
              value={form.transmission_fluid_type}
              onChange={(e) => setField('transmission_fluid_type', e.target.value)}
            />
          </Field>
          <Field id="spec_notes" label={t('detail.specs.notes')}>
            <Textarea
              id="spec_notes"
              value={form.maintenance_specs_notes}
              onChange={(e) => setField('maintenance_specs_notes', e.target.value)}
              rows={3}
            />
          </Field>
          <p className="text-xs text-text-mute flex items-start gap-2">
            <Wrench className="w-3.5 h-3.5 mt-0.5 shrink-0" aria-hidden />
            {t('detail.specs.hint')}
          </p>
        </div>
      </FormModalWrapper>
    </>
  )
}
