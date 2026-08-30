import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Droplets, Wrench } from 'lucide-react'
import { toast } from 'sonner'
import { Card, CardHeader, Button, Field, Input, NumberInput, Textarea, Mono } from '../ui'
import FormModalWrapper from '../FormModalWrapper'
import CardEditOverlay, { EDITABLE_CARD_CLASS } from './CardEditOverlay'
import vehicleService from '../../services/vehicleService'
import { emptyToNull, str } from '../../utils/formUtils'
import { parseDecimalInput } from '../../utils/decimalInput'
import { getActiveLocale } from '@/constants/i18n'
import {
  seedUnitField,
  unitFieldUnchanged,
  type QuantityFormat,
  type UnitFieldOrigin,
  type UnitFormat,
} from '../../utils/unitFormat'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import type { Vehicle, VehicleUpdate } from '../../types/vehicle'

interface VehicleSpecsPanelProps {
  vin: string
  vehicle: Vehicle
  onUpdated: (vehicle: Vehicle) => void
  /** When this counter increments, open the editor (used by Ask My Garage). */
  editRequestKey?: number
}

/**
 * The canonical origin of this form's two unit-bearing fields.
 *
 * Held INSIDE the form state, as on the tire form, so every `setForm` carries
 * the origins forward and there is no way to update one and forget the other.
 */
interface SpecFormOrigins {
  oil_capacity_liters: UnitFieldOrigin
  lug_nut_torque_nm: UnitFieldOrigin
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
  origins: SpecFormOrigins
}

/**
 * Read a unit-bearing field back into canonical storage, locale-aware.
 *
 * The locale-aware sibling of `canonicalFromUnitField`, which this form cannot
 * use: its numeric controls are `NumberInput`, which renders `type="text"` with
 * `inputMode="decimal"`, so a reader on a comma locale types `4,5` and that
 * helper's `Number()` would read it as NaN and silently store nothing. The
 * untouched-field rule is identical and shared, via `unitFieldUnchanged`: a
 * field the user did not touch posts back the canonical value it was seeded
 * from, never a re-conversion of what it displays.
 *
 * @param quantity The resolved adapter for this field's quantity.
 * @returns `null` for a field that cannot be read; the caller reports it.
 */
function readUnitField(
  typed: string,
  origin: UnitFieldOrigin,
  quantity: QuantityFormat,
  locale: string
): { ok: true; value: number | null } | { ok: false } {
  if (unitFieldUnchanged(typed, origin)) return { ok: true, value: origin.canonical }
  const parsed = parseDecimalInput(typed, locale)
  if (parsed.kind === 'invalid') return { ok: false }
  if (parsed.kind === 'empty') return { ok: true, value: null }
  return { ok: true, value: quantity.toCanonical(parsed.value) }
}

function seedForm(vehicle: Vehicle, u: UnitFormat): SpecForm {
  const oil = seedUnitField(
    vehicle.oil_capacity_liters != null ? Number(vehicle.oil_capacity_liters) : null,
    u.volume
  )
  const torque = seedUnitField(
    vehicle.lug_nut_torque_nm != null ? Number(vehicle.lug_nut_torque_nm) : null,
    u.torque
  )

  return {
    oil_viscosity: str(vehicle.oil_viscosity),
    oil_capacity: oil.display,
    oil_filter_part_number: str(vehicle.oil_filter_part_number),
    lug_nut_torque: torque.display,
    coolant_type: str(vehicle.coolant_type),
    brake_fluid_type: str(vehicle.brake_fluid_type),
    transmission_fluid_type: str(vehicle.transmission_fluid_type),
    maintenance_specs_notes: str(vehicle.maintenance_specs_notes),
    origins: { oil_capacity_liters: oil, lug_nut_torque_nm: torque },
  }
}

/**
 * Overview card for structured maintenance specs (oil, lug torque, fluids).
 *
 * Canonical storage stays liters / Nm. Display and entry resolve PER QUANTITY
 * through `useUnitFormat`, not through the binary imperial/metric flag the
 * first version branched on: that flag is collapsed out of VOLUME, so a reader
 * who chose litres with lb-ft was shown Nm, which is the disagreement issue
 * #152 was filed about.
 */
export default function VehicleSpecsPanel({
  vin,
  vehicle,
  onUpdated,
  editRequestKey = 0,
}: VehicleSpecsPanelProps) {
  const { t } = useTranslation('vehicles')
  const u = useUnitFormat()
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<SpecForm>(() => seedForm(vehicle, u))

  useEffect(() => {
    if (open) setForm(seedForm(vehicle, u))
  }, [open, vehicle, u])

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

  /** `origins` is excluded from the key type so a field write cannot replace it. */
  const setField = (key: Exclude<keyof SpecForm, 'origins'>, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  const handleSave = async () => {
    setSaving(true)
    try {
      const locale = getActiveLocale()

      const oil = readUnitField(
        form.oil_capacity,
        form.origins.oil_capacity_liters,
        u.volume,
        locale
      )
      if (!oil.ok) {
        toast.error(t('detail.specs.oilCapacityInvalid'))
        setSaving(false)
        return
      }

      const torque = readUnitField(
        form.lug_nut_torque,
        form.origins.lug_nut_torque_nm,
        u.torque,
        locale
      )
      if (!torque.ok) {
        toast.error(t('detail.specs.lugTorqueInvalid'))
        setSaving(false)
        return
      }

      const payload: VehicleUpdate = {
        oil_viscosity: emptyToNull(form.oil_viscosity),
        oil_capacity_liters: oil.value,
        oil_filter_part_number: emptyToNull(form.oil_filter_part_number),
        lug_nut_torque_nm: torque.value,
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

  /* One interpolated key per field, carrying the resolved unit, replacing the
   * pair of hardcoded 'gal'/'L' strings and the binary getTorqueUnit call. */
  const oilCapacityLabel = t('detail.specs.oilCapacityWithUnit', { unit: u.volume.label })
  const lugTorqueLabel = t('detail.specs.lugTorqueWithUnit', { unit: u.torque.label })

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
                  {u.volume.format(Number(vehicle.oil_capacity_liters))}
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
                  {u.torque.format(Number(vehicle.lug_nut_torque_nm))}
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
          <Field id="spec_oil_capacity" label={oilCapacityLabel}>
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
          <Field id="spec_lug_torque" label={lugTorqueLabel}>
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
