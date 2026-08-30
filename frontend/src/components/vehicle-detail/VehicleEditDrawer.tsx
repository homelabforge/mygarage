import { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm, type Resolver } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { Link } from 'react-router-dom'
import { Save, Droplets, Pencil, FileText, Radio } from 'lucide-react'
import { toast } from 'sonner'
import FormModalWrapper from '../FormModalWrapper'
import { Button, Field, Input, NumberInput, Select, Toggle, registerDecimal } from '../ui'
import vehicleService from '../../services/vehicleService'
import type { Vehicle, VehicleUpdate } from '../../types/vehicle'
import type { UnitSet } from '../../types/units'
import { makeVehicleEditSchema, type VehicleEditFormData, vehicleTypeOptions, NON_MOTORIZED_TYPES } from '../../schemas/vehicle'
import { FUEL_TYPE_VALUES, FUEL_TYPE_LABELS, isDieselFuelType } from '../../constants/fuel'
import { useUnitPreference } from '../../hooks/useUnitPreference'
import { useUnitFormat } from '../../hooks/useUnitFormat'
import { UnitFormatter } from '../../utils/units'
import { toLitersWirePrecision } from '../../utils/decimalSafe'
import { canonicalFromUnitField, seedUnitField, type UnitFieldOrigin } from '../../utils/unitFormat'
import { getUsageTracking } from '../../utils/usageTracking'
import { applyServerErrors } from '../../hooks/useApiFormErrors'
import { getActionErrorMessage } from '../../utils/httpErrorHandler'

/** Vehicles with no engine, VIN-decoded drivetrain, or DEF system. */
const NON_MOTORIZED: readonly string[] = NON_MOTORIZED_TYPES


/** Only these carry a Monroney label, so only these get the sticker section. */
const WINDOW_STICKER_TYPES = ['Car', 'Truck', 'SUV']

/**
 * The DEF tank-capacity EXAMPLE each volume token gets, as ONE physical tank.
 *
 * Keyed by the resolved token rather than selected by a binary system, for the
 * reason PropaneRecordForm's sibling table states: `system` is D8-collapsed
 * from volume, so `gal_uk` and `gal_us` both read 'imperial' and a UK account
 * was shown a US-gallon example beside a field labelled with ITS gallon.
 * 19 L / 3.78541 = 5.0 US gallons and / 4.54609 = 4.2 imperial ones.
 */
const DEF_CAPACITY_EXAMPLES: Readonly<Record<UnitSet['volume'], string>> = {
  L: '19.0',
  gal_us: '5.0',
  gal_uk: '4.2',
}

interface VehicleEditDrawerProps {
  open: boolean
  onClose: () => void
  vin: string
  vehicle: Vehicle
  /** Receives the server's updated vehicle after a successful save. */
  onUpdated: (vehicle: Vehicle) => void
  /** Opens the stored window-sticker PDF (blob download, owned by the parent). */
  onDownloadWindowSticker: () => void
  /** Opens the window-sticker upload/OCR drawer, which stacks over this one. */
  onUploadWindowSticker: () => void
  /** Opens the per-vehicle Torque Pro source drawer, which stacks over this one. */
  onManageTorqueSources: () => void
}

/**
 * Vehicle Settings sidecar — descended from the former /vehicles/:vin/edit
 * page, trimmed to the fields no info-card editor covers. Every other field
 * that page used to carry (year/make/model, VIN-decoded trim/body/drive/
 * doors/gvwr, displacement/cylinders/transmission, license plate, purchase
 * and sale info) now lives on an always-reachable card and its own drawer
 * (VehicleFieldsDrawer, PricingDrawer); seeding or rendering them here would
 * duplicate — and could race — those.
 *
 * `fuel_type` is the one exception kept here rather than on a card: it
 * directly gates the DEF Tracking section below (`isDieselFuelType`) and the
 * backend's `_check_def_capacity_gate` 400s a vehicle that ends up
 * non-diesel while still carrying DEF capacity, so fuel type and DEF
 * capacity must be edited together, in the same submit.
 *
 * What's carried over verbatim from the old page: react-hook-form +
 * makeVehicleEditSchema, the seed effect's `[open]`-only dependency array (below —
 * it must not re-run just because `t` got a new identity, or a language switch
 * mid-edit would discard everything typed), the DEF enable/clear state machine,
 * the canonical-litres conversion, and the motorized gate. What changed is the
 * surface (a Drawer, not a route) and the save tail — the page ended with
 * `window.location.href` for a hard reload; here the parent applies the saved
 * vehicle in place.
 *
 * The legacy `color` column is deliberately NOT edited here. The Basic
 * Information card writes `exterior_color`, display resolves
 * `exterior_color || color`, so a colour typed here would silently not appear
 * whenever the sticker/card value is set. Omitting the field is safe because
 * `optionalStringSchema` puts `.optional()` outside the transform — an
 * unregistered key short-circuits to `undefined`, JSON.stringify drops it, and
 * the backend's `exclude_unset=True` leaves the column untouched.
 */
export default function VehicleEditDrawer({
  open,
  onClose,
  vin,
  vehicle,
  onUpdated,
  onDownloadWindowSticker,
  onUploadWindowSticker,
  onManageTorqueSources,
}: VehicleEditDrawerProps) {
  const { t } = useTranslation('vehicles')
  const [defEnabled, setDefEnabled] = useState(false)
  // The vehicle the form is actually seeded from (the fresh refetch, or the
  // prop fallback if that refetch fails) — null until the seed resolves.
  // The render-time isMotorized gate (below — it guards the DEF Tracking
  // section) must read THIS, not the `vehicle` prop: the prop can disagree
  // with the fresh fetch on motorization, and gating a section on stale
  // truth while seeding form values from fresh truth registers fields the
  // fresh data never populates — `reset()` then submits them as explicit
  // `null`, clearing real columns.
  const [seedSource, setSeedSource] = useState<Vehicle | null>(null)
  const { units } = useUnitPreference()
  const u = useUnitFormat()

  /**
   * The DEF tank capacity's canonical origin, re-seeded on every open.
   *
   * A ref rather than state because nothing renders from it: `seedForm` writes
   * it in the same act that computes the field's display string, which is the
   * invariant that makes it an origin at all. It is re-seeded rather than
   * seeded once because this drawer re-`reset()`s from a FRESH fetch each time
   * it opens, so an origin captured at mount would describe a value the field
   * no longer holds.
   *
   * ★ It is here because this field had the identical shift the entry grid did
   * (ruling R4). The capacity was seeded through a display conversion that
   * rounds a gallon to two decimals and submitted through a helper that
   * converted that rounding straight back: a stored 37.9 L came back 37.892 on
   * a save that only renamed the vehicle. Same defect, same fix, one drawer
   * over from the three forms the ruling names.
   */
  const defCapacityOrigin = useRef<UnitFieldOrigin>({ canonical: null, display: '' })

  const isMotorized = seedSource ? !NON_MOTORIZED.includes(seedSource.vehicle_type) : false
  const hasWindowSticker = seedSource
    ? WINDOW_STICKER_TYPES.includes(seedSource.vehicle_type)
    : false

  // Zod bakes its messages in at construction, so the schema is rebuilt when
  // the language changes. Only the resolver depends on it — no fetch, no
  // reset() — so a rebuild can't discard what the user typed. (Distinct from
  // the seed effect below, which deliberately stays [open]-only.)
  const schema = useMemo(() => makeVehicleEditSchema(t), [t])

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    reset,
    setValue,
    watch,
    setError: setFieldError,
  } = useForm<VehicleEditFormData>({
    resolver: zodResolver(schema) as Resolver<VehicleEditFormData>,
    defaultValues: {},
  })

  // Which usage dimension(s) the form is currently configured for — primary
  // (usage_unit) plus the also-track toggle. Drives the Current Hours field's
  // visibility: it shows for hours-primary AND distance-primary+secondary
  // ("dual") vehicles, not just usage_unit === 'hours'.
  const usageTracking = getUsageTracking({
    usage_unit: watch('usage_unit'),
    secondary_usage_enabled: watch('secondary_usage_enabled'),
  })

  const watchedFuelType = watch('fuel_type')
  // The currently-selected (not saved) fuel type — drives DEF capacity gating
  // so switching the dropdown updates the UI immediately, mirroring the
  // server's diesel-only DEF capacity rule.
  const isDieselSelected = isDieselFuelType(watchedFuelType)

  // Shared by the "Enable DEF Tracking" toggle and the "Clear DEF Tank
  // Capacity" hint button — both turn tracking off and drop any stored value.
  const clearDefTracking = () => {
    setDefEnabled(false)
    setValue('def_tank_capacity_liters', undefined)
  }

  const seedForm = useCallback(async () => {
    // The `vehicle` prop can be stale: VehicleDetail fetches it once on mount
    // and, offline, falls back to a localStorage cache of arbitrary age.
    // MyGarage has multi-user vehicle sharing, so seeding a PUT of ~20 fields
    // from a stale read is a silent lost-update path. Refetch fresh, mirroring
    // the full-page editor this drawer replaced. detail-stats is a
    // supplementary read-aggregation (latest_hours, secondary_usage_enabled)
    // — its failure must not block the editor, so it swallows its own error
    // and the affected fields simply seed empty. The vehicle refetch gets the
    // same treatment: fall back to the prop if it fails (offline, transient
    // 5xx) — a stale seed still beats refusing to open the editor.
    const [fresh, detailStats] = await Promise.all([
      vehicleService.get(vin).catch(() => null),
      vehicleService.getDetailStats(vin).catch(() => null),
    ])
    const source = fresh ?? vehicle

    const formData: Record<string, unknown> = {
      nickname: source.nickname,
      vehicle_type: source.vehicle_type,
      usage_unit: source.usage_unit ?? 'distance',
      secondary_usage_enabled: detailStats?.secondary_usage_enabled ?? false,
      // R2-H1: `vehicle.current_hours` (the raw column) is retired as a read
      // source — it is no longer written on save, so it goes stale the moment
      // a fuel or service record carries a newer reading. Seed from the derived
      // latest reading; if detail-stats has none, leave it empty.
      current_hours: detailStats?.latest_hours != null ? Number(detailStats.latest_hours) : null,
      // Always included (propane on fifth wheels).
      fuel_type: source.fuel_type,
      def_tank_capacity_liters: (() => {
        // ★ THE ORIGIN IS WRITTEN ON EVERY PATH, INCLUDING THE ABSENT ONES, and
        // that is the whole reason this is not an early return. The two `return
        // undefined` branches used to leave the PREVIOUS open's origin in place,
        // which is exactly the state this ref's docstring says it exists to
        // prevent: open a vehicle with 19 L (origin `{19, '4.18'}`), turn DEF
        // tracking off, save, reopen on the fresh null, re-enable and type
        // `4.18`, and the stale origin claims the field is untouched and posts
        // 19 instead of the 19.003 that value converts to. `seedUnitField`
        // answers `{canonical: null, display: ''}` for an absent value, so the
        // reset is the same call rather than a second spelling of it.
        const cap = source.def_tank_capacity_liters
        const raw = cap == null ? NaN : typeof cap === 'string' ? parseFloat(cap) : Number(cap)
        defCapacityOrigin.current = seedUnitField(isNaN(raw) ? null : raw, u.volume)
        return defCapacityOrigin.current.display === ''
          ? undefined
          : Number(defCapacityOrigin.current.display)
      })(),
    }

    // DEF enabled follows the stored capacity, not the fuel type; the diesel
    // hint covers the suggestion when tracking is off.
    const hasTankCap =
      source.def_tank_capacity_liters != null && Number(source.def_tank_capacity_liters) > 0
    setDefEnabled(hasTankCap)

    // Publish the resolved source before reset() so the render-time isMotorized
    // gate (and the DEF section it admits) changes together with the field
    // values in the same tick — never gate on one snapshot while seeding from
    // another.
    setSeedSource(source)
    reset(formData as VehicleEditFormData)
    // `u.volume` rather than the whole resolved set: that is the only unit
    // decision this callback makes now, and `useUnitFormat` memoizes on the set
    // so the identity is as stable as `units` was.
  }, [vin, vehicle, reset, u.volume])

  // Reseed on each open transition only. Deliberately NOT keyed on `vehicle`:
  // the parent re-setting it while the drawer is open would reset the form
  // under the user. Mirrors PricingDrawer / VehicleFieldsDrawer.
  useEffect(() => {
    if (open) {
      // Clear first so the body cannot render against the PREVIOUS vehicle's
      // seed, then reseed. Deliberately NOT cleared on close: the Drawer keeps
      // the panel mounted through its exit transition, and blanking here makes
      // the content vanish mid-slide (same reason VehicleDetail.tsx:142-145
      // retains fieldsCard during the close animation).
      setSeedSource(null)
      seedForm()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const onSubmit = async (data: VehicleEditFormData) => {
    // DEF tracking on but no capacity entered → tiny positive sentinel
    // (canonical litres). Off → explicit null to clear the column.
    if (defEnabled && (!data.def_tank_capacity_liters || data.def_tank_capacity_liters <= 0)) {
      data.def_tank_capacity_liters = 0.01
    }
    if (!defEnabled) {
      data.def_tank_capacity_liters = null
    } else if (data.def_tank_capacity_liters != null) {
      // The entered value is in `units.volume`. An untouched field returns the
      // canonical litres it was seeded from; an edited one converts through the
      // same adapter, then takes the API's declared precision.
      const canonical = toLitersWirePrecision(
        canonicalFromUnitField(
          String(data.def_tank_capacity_liters),
          defCapacityOrigin.current,
          u.volume
        )
      )
      data.def_tank_capacity_liters = canonical ?? data.def_tank_capacity_liters
    }

    try {
      const updated = await vehicleService.update(vin, data as VehicleUpdate)
      onUpdated(updated)
      onClose()
    } catch (err) {
      // A non-422 failure (network drop, 500, plain throw) carries no field
      // problems at all — `unhandled` alone would stay empty and this branch
      // would never fire, silently dropping all feedback. `attached.length
      // === 0` catches that case; it's only skipped when every problem found
      // a field to land on.
      const { attached, unhandled } = applyServerErrors<VehicleEditFormData>(setFieldError, err, [
        'nickname',
        'vehicle_type',
        'fuel_type',
        'usage_unit',
        'current_hours',
        'def_tank_capacity_liters',
      ])
      if (attached.length === 0 || unhandled.length > 0) {
        toast.error(getActionErrorMessage(err, t('vehicleEditPage.saveAction')))
      }
    }
  }

  const fuelOptions = FUEL_TYPE_VALUES.map((value) => ({
    value,
    label: t(`forms:fuel.fuelTypes.${value}`, { defaultValue: FUEL_TYPE_LABELS[value] }),
  }))

  return (
    <FormModalWrapper
      isOpen={open}
      onClose={onClose}
      title={t('detail.settings.title')}
      icon={Pencil}
      width="lg"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isSubmitting}>
            {t('common:cancel')}
          </Button>
          <Button
            type="submit"
            form="vehicle-edit-form"
            variant="primary"
            icon={Save}
            loading={isSubmitting}
            disabled={isSubmitting}
          >
            {isSubmitting ? t('common:saving') : t('edit.saveChanges')}
          </Button>
        </>
      }
    >
      {!seedSource ? (
        // Nothing renders — and no field registers — until the seed resolves.
        // Rendering the form against the `vehicle` prop while a fresh
        // motorization verdict is still in flight is exactly the bug this
        // gate exists to prevent: a section mounting on stale truth registers
        // fields the fresh seed never populates, and reset() then submits
        // those as explicit `null`, clearing real columns.
        <div className="flex items-center justify-center p-6 text-sm text-text-mute">
          {t('common:loading')}
        </div>
      ) : (
      <form id="vehicle-edit-form" onSubmit={handleSubmit(onSubmit)} className="p-6 space-y-6">
        {/* Basic — one flat group, no section heading. DEF Tracking below is
            the one place a heading still earns its keep. */}
        <section>
          <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
            <Field id="nickname" label={t('edit.nickname')} required error={errors.nickname}>
              <Input
                id="nickname"
                type="text"
                {...register('nickname')}
                placeholder={t('vehicleEditPage.nicknamePlaceholder')}
                invalid={!!errors.nickname}
                disabled={isSubmitting}
              />
            </Field>

            {/* No blank option: vehicle_type is NOT NULL (the wizard's select
                has none either) — a null submit would 409 server-side and roll
                back the whole update. */}
            <Field id="vehicle_type" label={t('edit.vehicleType')} error={errors.vehicle_type}>
              {/* Deliberately no onChange resetting usage_unit. The wizard does
                  that because a new vehicle has no choice to destroy; here it is
                  an existing setting with hours history hanging off it, and
                  correcting a mis-typed vehicle_type would silently flip a Boat
                  from hours to distance and hide its Hours tab. */}
              <Select
                id="vehicle_type"
                {...register('vehicle_type')}
                invalid={!!errors.vehicle_type}
                disabled={isSubmitting}
                options={vehicleTypeOptions(t)}
              />
            </Field>

            {/* Always included (propane on fifth wheels) — the one card
                field VehicleFieldsDrawer does NOT edit, because it also
                gates the DEF section directly below. */}
            <Field id="fuel_type" label={t('edit.fuelType')} error={errors.fuel_type}>
              <Select id="fuel_type" {...register('fuel_type')} invalid={!!errors.fuel_type} disabled={isSubmitting} placeholder="—" options={fuelOptions} />
            </Field>

            <Field id="usage_unit" label={t('edit.usageTracking')} error={errors.usage_unit}>
              <Select
                id="usage_unit"
                {...register('usage_unit')}
                invalid={!!errors.usage_unit}
                disabled={isSubmitting}
                options={[
                  { value: 'distance', label: t('edit.usageDistance') },
                  { value: 'hours', label: t('edit.usageHours') },
                ]}
              />
            </Field>

            <div className="mb-4 flex items-end">
              {/* Toggle, not Checkbox: this is a single on/off setting, which is
                  the distinction the primitives draw (Checkbox is for picking
                  items from a set). Toggle is controlled-only — it takes
                  `checked`/`onChange(next)` and cannot accept a register()
                  spread — so it is wired through watch/setValue instead. */}
              <Toggle
                id="secondary_usage_enabled"
                checked={!!watch('secondary_usage_enabled')}
                disabled={isSubmitting}
                onChange={(next) =>
                  setValue('secondary_usage_enabled', next, { shouldDirty: true })
                }
                label={
                  watch('usage_unit') === 'hours'
                    ? t('edit.alsoTrackDistance')
                    : t('edit.alsoTrackHours')
                }
              />
            </div>

            {usageTracking.tracksHours && (
              <Field id="current_hours" label={t('edit.currentHours')} error={errors.current_hours}>
                <NumberInput
                  id="current_hours"
                  {...registerDecimal(register, 'current_hours')}
                  placeholder={t('vehicleEditPage.currentHoursPlaceholder')}
                  invalid={!!errors.current_hours}
                  disabled={isSubmitting}
                />
              </Field>
            )}
          </div>
        </section>

        {/* DEF Tracking — motorized, OR a non-motorized vehicle that already
            carries stored DEF capacity (a nonsense data state, but one with
            no other UI path to clear it: the Clear button lives inside this
            same gate, so a bare `isMotorized` check strands that vehicle on
            a backend 400 the moment fuel type changes away from diesel). */}
        {(isMotorized || defEnabled) && (
          <section>
            <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-text">
              <Droplets className="h-5 w-5" aria-hidden="true" />
              {t('edit.defTracking')}
            </h3>
            <div className="space-y-4">
              <Toggle
                id="def_enabled"
                checked={defEnabled}
                disabled={isSubmitting}
                onChange={(next) => {
                  if (next) setDefEnabled(true)
                  else clearDefTracking()
                }}
                label={t('edit.enableDefTracking')}
              />

              {isDieselSelected && !defEnabled && (
                <p className="text-sm text-warning">{t('edit.dieselDefHint')}</p>
              )}

              {defEnabled && (
                <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
                  <Field
                    id="def_tank_capacity_liters"
                    label={t('edit.defTankCapacity')}
                    unit={UnitFormatter.getVolumeUnit(units)}
                    error={errors.def_tank_capacity_liters}
                    hint={isDieselSelected ? t('edit.defTankCapacityHint') : undefined}
                  >
                    <NumberInput
                      id="def_tank_capacity_liters"
                      {...registerDecimal(register, 'def_tank_capacity_liters')}
                      disabled={isSubmitting || !isDieselSelected}
                      invalid={!!errors.def_tank_capacity_liters}
                      placeholder={DEF_CAPACITY_EXAMPLES[units.volume]}
                    />
                    {!isDieselSelected && (
                      <div className="mt-1 space-y-1">
                        <p className="text-xs text-warning">
                          {t('edit.defCapacityRequiresDieselHint')}
                        </p>
                        <button
                          type="button"
                          onClick={clearDefTracking}
                          className="cursor-pointer text-xs text-primary hover:underline"
                        >
                          {t('edit.clearDefTankCapacity')}
                        </button>
                      </div>
                    )}
                  </Field>
                </div>
              )}
            </div>
          </section>
        )}

        {/* Window Sticker — cars/trucks/SUVs only, moved here from the Overview
            tab. Read-only display plus two actions; nothing here registers with
            the form, so the stale-seed null-clearing hazard the DEF section
            guards against does not apply. That is also why the displayed values
            come from the `vehicle` prop rather than `seedSource`: the parent
            refetches into the prop when an upload succeeds, so this section
            reflects a new sticker immediately instead of waiting for the drawer
            to be reopened. Only the type gate reads `seedSource`, keeping the
            rule that every gate in this form follows the fresh seed.

            The two raw <button>s carry an explicit type="button": they sit
            inside #vehicle-edit-form, whose submit belongs to the footer Save.
            (The <Button> primitive already defaults to type="button".) */}
        {hasWindowSticker && (
          <section>
            <div className="mb-4 flex items-center justify-between gap-3">
              <h3 className="flex items-center gap-2 text-lg font-semibold text-text">
                <FileText className="h-5 w-5" aria-hidden="true" />
                {t('detail.windowSticker')}
              </h3>
              <Link
                to={`/vehicles/${vin}/window-sticker-test`}
                className="rounded-control bg-surface-2 px-2 py-1 text-xs text-text-mute transition-colors hover:text-(--accent-fg)"
              >
                {t('detail.misc.testOcr')}
              </Link>
            </div>

            {vehicle.window_sticker_file_path ? (
              <div className="space-y-3">
                <button
                  type="button"
                  onClick={onDownloadWindowSticker}
                  className="w-full cursor-pointer"
                >
                  <div className="flex h-20 items-center justify-center gap-3 overflow-hidden rounded-panel border border-border bg-surface-2 transition-colors hover:bg-surface">
                    <FileText className="h-8 w-8 text-(--accent-fg)" />
                    <div className="text-left">
                      <p className="text-sm font-medium text-text">{t('detail.viewWindowSticker')}</p>
                      <p className="text-xs text-text-mute">{t('detail.clickToOpenPDF')}</p>
                    </div>
                  </div>
                </button>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-faint">
                  {vehicle.window_sticker_parser_used && (
                    <span>{t('detail.misc.parser', { parser: vehicle.window_sticker_parser_used })}</span>
                  )}
                  {vehicle.window_sticker_confidence_score && (
                    <span>
                      {t('detail.misc.confidence', {
                        score: Number(vehicle.window_sticker_confidence_score).toFixed(0),
                      })}
                    </span>
                  )}
                  {vehicle.window_sticker_extracted_vin && (
                    <span
                      className={
                        vehicle.window_sticker_extracted_vin === vehicle.vin
                          ? 'text-success'
                          : 'text-warning'
                      }
                    >
                      {vehicle.window_sticker_extracted_vin === vehicle.vin
                        ? `✓ ${t('detail.misc.vinVerified')}`
                        : `⚠ ${t('detail.misc.vinMismatch')}`}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={onUploadWindowSticker}
                  className="cursor-pointer text-sm text-text-mute transition-colors hover:text-text"
                >
                  {t('detail.replaceSticker')}
                </button>
              </div>
            ) : (
              <div className="rounded-panel border border-dashed border-border py-4 text-center">
                <FileText className="mx-auto mb-2 h-10 w-10 text-text-mute opacity-50" />
                <p className="mb-3 text-sm text-text-mute">{t('detail.noWindowSticker')}</p>
                <Button variant="primary" size="sm" onClick={onUploadWindowSticker}>
                  {t('detail.uploadWindowSticker')}
                </Button>
              </div>
            )}
          </section>
        )}

        {/* Connected Devices — moved off the Overview tab, where it was a whole
            masonry card spending its entire body on one description line and
            one launch button. Deliberately ungated on vehicle type, exactly as
            that card was: a Torque source is revoked through the same drawer it
            is created in, so hiding the launcher for (say) a trailer would
            strand any source already registered against one. */}
        <section>
          <h3 className="mb-4 flex items-center gap-2 text-lg font-semibold text-text">
            <Radio className="h-5 w-5" aria-hidden="true" />
            {t('detail.connectedDevices')}
          </h3>
          <div className="flex items-center justify-between gap-4">
            <p className="text-sm text-text-mute">{t('forms:modal.torque.description')}</p>
            <Button
              variant="secondary"
              icon={Radio}
              onClick={onManageTorqueSources}
              title={t('forms:modal.torque.launchButtonTooltip')}
            >
              {t('forms:modal.torque.launchButton')}
            </Button>
          </div>
        </section>
      </form>
      )}
    </FormModalWrapper>
  )
}
