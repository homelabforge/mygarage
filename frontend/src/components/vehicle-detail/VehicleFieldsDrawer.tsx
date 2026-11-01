import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Info, FileText, Gauge, Shield, type LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from '../FormModalWrapper'
import { Button, Field, Input, NumberInput, Textarea } from '../ui'
import vehicleService from '../../services/vehicleService'
import { str, emptyToNull } from '../../utils/formUtils'
import type { Vehicle, VehicleUpdate } from '../../types/vehicle'
import { getActiveLocale } from '../../constants/i18n'
import { parseDecimalInput } from '../../utils/decimalInput'
import { INVALID_NUMBER } from '../../schemas/shared'
import { makeVehicleWholeNumberFields } from '../../schemas/vehicle'

/** The four Overview info cards that open this shared editor sidecar. */
export type VehicleCardKey = 'basic' | 'details' | 'powertrain' | 'warranty'

type FieldKind = 'text' | 'number' | 'multiline'

/** The number fields here, each checked by the edit form's own rule. */
type WholeNumberKey = keyof ReturnType<typeof makeVehicleWholeNumberFields>

interface FieldSpec {
  /** Vehicle column — present on both the update and response schemas. */
  key: keyof VehicleUpdate & keyof Vehicle
  /** vehicles-namespace translation key for the label. */
  label: string
  kind: FieldKind
  /** Seed fallback order (first non-empty wins). Defaults to `[key]`. Used so
   *  "Exterior color" seeds from the sticker field, then the legacy `color`. */
  seedKeys?: (keyof Vehicle)[]
}

interface CardConfig {
  titleKey: string
  icon: LucideIcon
  fields: FieldSpec[]
}

/** The field set each card edits. */
function getCardConfig(card: VehicleCardKey): CardConfig {
  switch (card) {
    case 'basic':
      return {
        titleKey: 'detail.basicInformation',
        icon: Info,
        fields: [
          { key: 'year', label: 'edit.year', kind: 'number' },
          { key: 'make', label: 'edit.make', kind: 'text' },
          { key: 'model', label: 'edit.model', kind: 'text' },
          { key: 'license_plate', label: 'edit.licensePlate', kind: 'text' },
          {
            key: 'exterior_color',
            label: 'detail.misc.exteriorColor',
            kind: 'text',
            seedKeys: ['exterior_color', 'color'],
          },
          { key: 'interior_color', label: 'detail.misc.interiorColor', kind: 'text' },
          { key: 'assembly_location', label: 'detail.misc.assemblyLocation', kind: 'text' },
        ],
      }
    case 'details':
      return {
        titleKey: 'detail.vehicleDetails',
        icon: FileText,
        fields: [
          { key: 'trim', label: 'edit.trim', kind: 'text' },
          { key: 'body_class', label: 'edit.bodyClass', kind: 'text' },
          { key: 'drive_type', label: 'edit.driveType', kind: 'text' },
          { key: 'doors', label: 'edit.doors', kind: 'number' },
          { key: 'gvwr_class', label: 'detail.misc.gvwrClass', kind: 'text' },
          { key: 'wheel_specs', label: 'detail.misc.wheels', kind: 'text' },
          { key: 'tire_specs', label: 'detail.misc.tires', kind: 'text' },
        ],
      }
    case 'powertrain':
      return {
        titleKey: 'detail.powertrain',
        icon: Gauge,
        fields: [
          { key: 'displacement_l', label: 'detail.misc.displacement', kind: 'text' },
          { key: 'cylinders', label: 'edit.cylinders', kind: 'number' },
          { key: 'sticker_engine_description', label: 'detail.misc.engine', kind: 'multiline' },
          { key: 'transmission_type', label: 'edit.transmissionType', kind: 'text' },
          { key: 'transmission_speeds', label: 'edit.transmissionSpeeds', kind: 'text' },
          {
            key: 'sticker_transmission_description',
            label: 'detail.misc.transmission',
            kind: 'multiline',
          },
          { key: 'sticker_drivetrain', label: 'detail.misc.drivetrain', kind: 'text' },
        ],
      }
    case 'warranty':
      return {
        titleKey: 'detail.warranty',
        icon: Shield,
        fields: [
          { key: 'warranty_basic', label: 'detail.misc.basic', kind: 'text' },
          { key: 'warranty_powertrain', label: 'detail.powertrain', kind: 'text' },
        ],
      }
  }
}

/** Seed the string-valued form from the vehicle, honoring seedKeys fallbacks. */
function seedForm(config: CardConfig, v: Vehicle): Record<string, string> {
  const out: Record<string, string> = {}
  for (const f of config.fields) {
    const keys = f.seedKeys ?? [f.key]
    let value = ''
    for (const k of keys) {
      const s = str(v[k])
      if (s !== '') {
        value = s
        break
      }
    }
    out[f.key] = value
  }
  return out
}

interface VehicleFieldsDrawerProps {
  open: boolean
  onClose: () => void
  vehicle: Vehicle
  vin: string
  /** Which card's fields to edit. Retained during the close animation, so it
   *  may briefly stay set while `open` is false. Null before the first open. */
  card: VehicleCardKey | null
  /** Unused inside the component (see `_isMotorized` below) — kept optional
   *  rather than required so the interface stops implying it drives
   *  behaviour. `VehicleDetail.tsx` still passes it; that's harmless. */
  isMotorized?: boolean
  /** Receives the server's updated vehicle after a successful save. */
  onUpdated: (vehicle: Vehicle) => void
}

/**
 * Shared edit sidecar for the Overview info cards (Basic Information, Vehicle
 * Details, Powertrain, Warranty). One config-driven form rather than four
 * near-identical drawers. Like the pricing sidecar, edits are local until Save
 * commits them in one partial PUT, then the drawer closes.
 */
export default function VehicleFieldsDrawer({
  open,
  onClose,
  vehicle,
  vin,
  card,
  // Only ever fed the Details-card fuel_type FieldSpec, which moved to the
  // settings sidecar. The prop stays on the interface — VehicleDetail still
  // passes it — but getCardConfig no longer reads it.
  isMotorized: _isMotorized,
  onUpdated,
}: VehicleFieldsDrawerProps) {
  const { t } = useTranslation('vehicles')
  const [form, setForm] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const wholeNumbers = useMemo(() => makeVehicleWholeNumberFields(t), [t])
  // Snapshot of the seeded values, so save can send only the fields the user
  // actually changed (a true partial PUT). Load-bearing for the exterior-color
  // duality: `exterior_color` seeds from the legacy `color`, so an untouched
  // save must NOT write it back — that would promote `color` into
  // `exterior_color` and permanently mask it under the `exterior_color || color`
  // display precedence.
  const initialRef = useRef<Record<string, string>>({})

  const config = card ? getCardConfig(card) : null

  useEffect(() => {
    // Reseed from the vehicle each time the drawer opens on a card. Save closes
    // it, so there is no open-state reseed race (mirrors PricingDrawer).
    if (open && config) {
      const seeded = seedForm(config, vehicle)
      setForm(seeded)
      setErrors({})
      initialRef.current = seeded
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, card])

  const set =
    (key: string) =>
    (e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>): void =>
      setForm((prev) => ({ ...prev, [key]: e.target.value }))

  const handleSave = async (): Promise<void> => {
    if (!config) return
    // Dirty-diff: only changed fields go in the payload; unchanged ones are
    // omitted and left untouched server-side (exclude_unset).
    const payload: Record<string, string | number | null> = {}
    const found: Record<string, string> = {}
    for (const f of config.fields) {
      const current = form[f.key] ?? ''
      if (current === (initialRef.current[f.key] ?? '')) continue
      if (f.kind !== 'number') {
        payload[f.key] = emptyToNull(current)
        continue
      }
      // Read in the user's language, then the edit form's own year/doors/cylinders rule.
      const parsed = parseDecimalInput(current, getActiveLocale())
      const typed = parsed.kind === 'value' ? parsed.value : parsed.kind === 'invalid' ? INVALID_NUMBER : null
      const checked = wholeNumbers[f.key as WholeNumberKey].safeParse(typed)
      if (checked.success) payload[f.key] = checked.data ?? null
      else found[f.key] = checked.error.issues[0]?.message ?? ''
    }
    setErrors(found)
    if (Object.keys(found).length > 0) return
    // This field IS the overview's colour (`exterior_color || color`), so a
    // clear has to take the legacy `color` with it or that comes straight back.
    // The sticker review doesn't do this: there a clear means the OCR was wrong.
    if ('exterior_color' in payload && payload.exterior_color === null && vehicle.color) {
      payload.color = null
    }
    if (Object.keys(payload).length === 0) {
      onClose()
      return
    }
    setSaving(true)
    try {
      const updated = await vehicleService.update(vin, payload as VehicleUpdate)
      onUpdated(updated)
      onClose()
    } catch {
      toast.error(t('detail.cardEdit.saveError'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <FormModalWrapper
      isOpen={open}
      onClose={onClose}
      title={config ? t('detail.cardEdit.title', { section: t(config.titleKey) }) : ''}
      icon={config?.icon ?? Info}
      width="md"
      footer={
        <Button variant="primary" onClick={handleSave} loading={saving} disabled={!config}>
          {t('common:save')}
        </Button>
      }
    >
      {config && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {config.fields.map((f) => {
            const id = `vfd_${f.key}`
            const value = form[f.key] ?? ''
            return (
              <div key={f.key} className={f.kind === 'multiline' ? 'sm:col-span-2' : ''}>
                <Field id={id} label={t(f.label)} error={errors[f.key]}>
                  {f.kind === 'multiline' ? (
                    <Textarea id={id} rows={2} value={value} onChange={set(f.key)} />
                  ) : f.kind === 'number' ? (
                    <NumberInput id={id} value={value} onChange={set(f.key)} invalid={!!errors[f.key]} />
                  ) : (
                    <Input id={id} type="text" value={value} onChange={set(f.key)} />
                  )}
                </Field>
              </div>
            )
          })}
        </div>
      )}
    </FormModalWrapper>
  )
}
