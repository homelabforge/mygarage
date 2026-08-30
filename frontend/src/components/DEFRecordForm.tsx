import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Save } from 'lucide-react'
import FormModalWrapper from './FormModalWrapper'
import type { DEFRecord, DEFRecordCreate } from '../types/def'
import { makeDefRecordSchema, type DefRecordFormData } from '../schemas/def'
import { FormError } from './FormError'
import { useCreateDEFRecord, useUpdateDEFRecord } from '../hooks/queries/useDEFRecords'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter } from '../utils/units'
import {
  canonicalFromPriceField,
  readNumber,
  seedPriceField,
  toLitersWirePrecision,
  type PriceFieldOrigin,
} from '../utils/decimalSafe'
import { useUnitFormat } from '../hooks/useUnitFormat'
import { canonicalFromUnitField, seedUnitField, type UnitFieldOrigin } from '../utils/unitFormat'
import { useOnUserEdit } from '../hooks/useOnUserEdit'
import { formatDateForInput } from '../utils/dateUtils'
import CurrencyInputPrefix from './common/CurrencyInputPrefix'
import { Button, Field, Input, NumberInput, Textarea, registerDecimal } from './ui'
import { applyServerErrors } from '../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../utils/httpErrorHandler'

// `labelKey` is translated at render time; the fraction labels are numerals and
// stay as-is (they are not prose).
const FILL_LEVEL_PRESETS = [
  { label: null, labelKey: 'defRecordForm.fillLevelFull', value: 100 },
  { label: '3/4', labelKey: null, value: 75 },
  { label: '1/2', labelKey: null, value: 50 },
  { label: '1/4', labelKey: null, value: 25 },
] as const

const SOURCE_SUGGESTIONS = [
  'Truck Stop / Station Nozzle',
  'Auto Parts Store',
  'Walmart',
  'Amazon',
  'Other Store',
] as const

const BRAND_SUGGESTIONS = [
  'BlueDEF',
  'Peak Blue',
  'Prestone',
  'Mopar',
  'Fleetguard',
] as const

interface DEFRecordFormProps {
  vin: string
  record?: DEFRecord
  onClose: () => void
  onSuccess: () => void
}

export default function DEFRecordForm({
  vin,
  record,
  onClose,
  onSuccess
}: DEFRecordFormProps) {
  const { t } = useTranslation('forms')
  const isEdit = !!record
  const [error, setError] = useState<string | null>(null)
  const createMutation = useCreateDEFRecord(vin)
  const updateMutation = useUpdateDEFRecord(vin)
  const { units } = useUnitPreference()
  // Per-quantity adapters. The binary `system` is D8-collapsed from VOLUME,
  // so it cannot answer for the odometer: a client resolving
  // `{volume: 'L', distance: 'mi'}` reads 'metric' out of it for a distance
  // they chose in miles, and the mirror client resolving gallons with
  // kilometres had a stored kilometre reading converted INTO miles.
  const u = useUnitFormat()

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed.
  const schema = useMemo(() => makeDefRecordSchema(t), [t])

  /**
   * The odometer's canonical origin.
   *
   * A display unit that only formats corrupts data (binding decision D2):
   * 72420.5 km reads as 45000 mi, and 45000 mi converts back to 72420.3.
   * `seedUnitField` records what the field was populated from so
   * `canonicalFromUnitField` can hand that value straight back while the
   * field still reads what it was seeded with, and a user who opens a record
   * to fix the brand does not move the reading.
   *
   * Lazily seeded for the same reason `defaultValues` is computed once: an
   * origin that moved on re-render would stop being an origin.
   *
   * ★ VOLUME AND PRICE ARE HERE NOW, and the comment they replace claimed
   * "Task 2 made their round trip exact by other means". It did not. Task 2
   * put both on the resolved `UnitSet`, which fixed WHICH gallon they used and
   * left the round trip itself reconverting a rounded display: a stored
   * 37.9 L seeded a US-gallon field as 10.01 and came back 37.892 on a save
   * the user never made an edit in. Plan 3b ruling R4 gives that shift to this
   * task, and the origin is the whole of the fix.
   */
  const [odometerOrigin] = useState<UnitFieldOrigin>(() =>
    seedUnitField(readNumber(record?.odometer_km), u.distance)
  )

  /** The volume field's canonical origin, in `units.volume`. */
  const [litersOrigin] = useState<UnitFieldOrigin>(() =>
    seedUnitField(readNumber(record?.liters), u.volume)
  )

  /**
   * The price field's canonical origin, in $ per `units.volume`.
   *
   * This form's basis is fixed: it seeds and submits `per_volume`, so the
   * basis leg of `canonicalFromPriceField` cannot fire here. It is passed
   * rather than omitted because a price origin without one is not a price
   * origin, and the fuel form beside this one CAN move it.
   */
  const [priceOrigin] = useState<PriceFieldOrigin>(() =>
    seedPriceField(record?.price_per_unit, units, 'per_volume')
  )

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setValue,
    watch,
    subscribe,
    setError: setFieldError,
  } = useForm<DefRecordFormData>({
    resolver: zodResolver(schema) as Resolver<DefRecordFormData>,
    defaultValues: {
      date: formatDateForInput(record?.date),
      // Seeded in `units.distance`, and the submit converts back through the
      // SAME adapter. `readNumber('')` is undefined, which is the empty field.
      odometer_km: readNumber(odometerOrigin.display),
      // Seeded in `units.volume` and in $ per that unit, and the submit reads
      // both back through the SAME origins, so reopening a record neither
      // re-converts on a different gallon nor reconverts its own rounding.
      liters: readNumber(litersOrigin.display),
      price_per_unit: readNumber(priceOrigin.display),
      cost: readNumber(record?.cost),
      fill_level: (() => {
        const fl = readNumber(record?.fill_level)
        return fl !== undefined ? fl * 100 : undefined // Store as 0.00-1.00, display as 0-100
      })(),
      source: record?.source || '',
      brand: record?.brand || '',
      notes: record?.notes || '',
    },
  })

  // Cost follows volume and price on user edits only (see useOnUserEdit), so
  // reopening a record cannot overwrite a stored total that was not exactly
  // volume by price.
  useOnUserEdit(subscribe, ['liters', 'price_per_unit'], (values) => {
    const litersNum = readNumber(values.liters)
    const priceNum = readNumber(values.price_per_unit)
    if (litersNum === undefined || priceNum === undefined) return
    setValue('cost', parseFloat((litersNum * priceNum).toFixed(2)))
  })

  const onSubmit = async (data: DefRecordFormData) => {
    setError(null)

    try {
      const payload = {
        vin,
        date: data.date,
        // Back through `units.distance`. An untouched field returns the
        // canonical value it was seeded from rather than a re-conversion of a
        // rounded display, and `readNumber` absorbs `registerDecimal`'s
        // INVALID_NUMBER symbol, which throws on every implicit coercion.
        odometer_km:
          canonicalFromUnitField(
            String(readNumber(data.odometer_km) ?? ''),
            odometerOrigin,
            u.distance
          ) ?? undefined,
        // ★ Volume and price convert through ONE resolved set (defect L1), and
        // an untouched field returns the canonical value it was seeded from
        // rather than a re-conversion of a rounded display (ruling R4).
        // `toLitersWirePrecision` is the API's declared 3 decimals, which the
        // protocol deliberately does not apply: pydantic 422s a fourth.
        liters:
          toLitersWirePrecision(
            canonicalFromUnitField(
              String(readNumber(data.liters) ?? ''),
              litersOrigin,
              u.volume
            )
          ) ?? undefined,
        price_per_unit:
          canonicalFromPriceField(
            String(readNumber(data.price_per_unit) ?? ''),
            priceOrigin,
            units,
            'per_volume'
          ) ?? undefined,
        cost: data.cost,
        fill_level: data.fill_level !== undefined ? data.fill_level / 100 : undefined, // Convert % to 0.00-1.00
        source: data.source || undefined,
        brand: data.brand || undefined,
        notes: data.notes || undefined,
      }

      if (isEdit && record) {
        await updateMutation.mutateAsync({ id: record.id, ...payload })
      } else {
        await createMutation.mutateAsync(payload as DEFRecordCreate)
      }

      onSuccess()
      onClose()
    } catch (err) {
      // attached.length === 0 catches a non-422 failure (network drop, 500):
      // it carries no field problems at all, so `unhandled` alone would stay
      // empty and this banner would never show.
      const { attached, unhandled } = applyServerErrors<DefRecordFormData>(setFieldError, err, [
        'date',
        'odometer_km',
        'fill_level',
        'liters',
        'price_per_unit',
        'cost',
        'source',
        'brand',
        'notes',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('def.saveAction')))
      }
    }
  }

  return (
    <FormModalWrapper
      title={isEdit ? t('def.editTitle') : t('def.createTitle')}
      onClose={onClose}
      width="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button type="submit" form="def-record-form" variant="primary" icon={Save} loading={isSubmitting}>
            {isSubmitting ? t('common:saving') : isEdit ? t('common:update') : t('common:create')}
          </Button>
        </>
      }
    >
        <form id="def-record-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <Field id="date" label={t('common:date')} required error={errors.date}>
              <Input type="date" id="date" {...register('date')} invalid={!!errors.date} disabled={isSubmitting} />
            </Field>
            <Field id="odometer_km" label={t('common:mileage')} unit={u.distance.label} error={errors.odometer_km}>
              <NumberInput id="odometer_km" {...registerDecimal(register, 'odometer_km')} placeholder="55000" invalid={!!errors.odometer_km} disabled={isSubmitting} />
            </Field>
          </div>

          {/* Fill Level */}
          <div>
            <label className="block text-sm font-medium text-text mb-2">{t('def.tankLevelAfterFill')}</label>
            <div className="flex gap-2 mb-2">
              {FILL_LEVEL_PRESETS.map((preset) => (
                <Button
                  key={preset.value}
                  size="sm"
                  variant={watch('fill_level') === preset.value ? 'primary' : 'secondary'}
                  onClick={() => setValue('fill_level', preset.value)}
                >
                  {preset.labelKey ? t(preset.labelKey) : preset.label}
                </Button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <div className="w-24 shrink-0">
                <NumberInput
                  id="fill_level"
                  {...registerDecimal(register, 'fill_level')}
                  placeholder="75"
                  invalid={!!errors.fill_level}
                  disabled={isSubmitting}
                />
              </div>
              <span className="text-sm text-text-mute">%</span>
              {watch('fill_level') !== undefined && !isNaN(watch('fill_level') ?? NaN) && (
                <div className="flex-1 h-4 rounded-full border border-border bg-surface-2 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      (watch('fill_level') ?? 0) > 50 ? 'bg-success' :
                      (watch('fill_level') ?? 0) > 25 ? 'bg-warning' : 'bg-danger'
                    }`}
                    style={{ width: `${Math.min(100, Math.max(0, watch('fill_level') ?? 0))}%` }}
                  />
                </div>
              )}
            </div>
            <FormError error={errors.fill_level} />
          </div>

          {/* Volume and Pricing */}
          <div className="grid grid-cols-3 gap-4">
            <Field id="liters" label={UnitFormatter.getVolumeUnit(units)} error={errors.liters}>
              <NumberInput id="liters" {...registerDecimal(register, 'liters')} placeholder="5.500" invalid={!!errors.liters} disabled={isSubmitting} />
            </Field>
            <Field id="price_per_unit" label={`${t('fuel.pricePer')}/${UnitFormatter.getVolumeUnit(units)}`} error={errors.price_per_unit}>
              <div className="relative">
                <CurrencyInputPrefix />
                <NumberInput id="price_per_unit" {...registerDecimal(register, 'price_per_unit')} placeholder="4.500" invalid={!!errors.price_per_unit} disabled={isSubmitting} className="pl-7" />
              </div>
            </Field>
            <Field id="cost" label={t('common:totalCost')} error={errors.cost} hint={t('common:autoCalculated')}>
              <div className="relative">
                <CurrencyInputPrefix />
                <NumberInput id="cost" {...registerDecimal(register, 'cost')} placeholder="24.75" invalid={!!errors.cost} disabled={isSubmitting} className="pl-7" />
              </div>
            </Field>
          </div>

          {/* Source */}
          <Field id="source" label={t('def.wherePurchased')} error={errors.source}>
            <Input type="text" id="source" list="source-suggestions" {...register('source')} placeholder={t('defRecordForm.sourcePlaceholder')} invalid={!!errors.source} disabled={isSubmitting} />
            <datalist id="source-suggestions">
              {SOURCE_SUGGESTIONS.map((s) => (<option key={s} value={s} />))}
            </datalist>
          </Field>

          {/* Brand */}
          <Field id="brand" label={t('def.brand')} error={errors.brand}>
            <Input type="text" id="brand" list="brand-suggestions" {...register('brand')} placeholder="e.g., BlueDEF" invalid={!!errors.brand} disabled={isSubmitting} />
            <datalist id="brand-suggestions">
              {BRAND_SUGGESTIONS.map((b) => (<option key={b} value={b} />))}
            </datalist>
          </Field>

          {/* Notes */}
          <Field id="notes" label={t('common:notes')} error={errors.notes}>
            <Textarea id="notes" rows={3} {...register('notes')} placeholder={t('common:additionalNotes')} invalid={!!errors.notes} disabled={isSubmitting} />
          </Field>
        </form>
    </FormModalWrapper>
  )
}
