import { lazy, Suspense, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { Calendar, FileText, Radio } from 'lucide-react'
import { Card, CardHeader, Mono, Button } from '../ui'
import type { Vehicle } from '../../types/vehicle'
import type { LastLocation } from '../../types/trips'
import { formatCurrency } from '../../utils/formatUtils'
import { UnitFormatter } from '../../utils/units'
import { useUnitPreference } from '../../hooks/useUnitPreference'
import { formatDateForDisplay } from '../../utils/dateUtils'
import { useCurrencyPreference } from '../../hooks/useCurrencyPreference'
import { useDateLocale } from '../../hooks/useDateLocale'
import { useTimeFormat } from '../../hooks/useTimeFormat'
import { formatDateTime } from '../../utils/parseAPITimestamp'
import TransferHistorySection from '../TransferHistorySection'
import type { EquipmentExpandSignal } from '../../pages/VehicleDetail'

// Lazy-load map component — keeps Leaflet's ~150KB out of the main bundle
const LastLocationMap = lazy(() => import('../maps/LastLocationMap'))

interface VehicleOverviewTabProps {
  vin: string
  vehicle: Vehicle
  lastLocation: LastLocation | null
  expandEquipment: EquipmentExpandSignal | null
  onOpenModal: (modal: 'torqueSource' | 'windowSticker') => void
  onDownloadWindowSticker: () => void
}

/**
 * Vehicle Detail Overview tab content. Mechanically extracted from
 * VehicleDetail.tsx (P5 Task 1, verbatim — no restyle). Equipment expand/scroll
 * wiring lands in Task 4 (behavioral only); the Card/CardHeader/Mono restyle
 * lands in Task 7, which preserves the refs + effect below.
 */
export default function VehicleOverviewTab({
  vin, vehicle, lastLocation, expandEquipment, onOpenModal, onDownloadWindowSticker,
}: VehicleOverviewTabProps) {
  const { t } = useTranslation('vehicles')
  const { system: unitSystem } = useUnitPreference()
  const dateLocale = useDateLocale()
  const { currencyCode, locale } = useCurrencyPreference()
  const { timeFormat } = useTimeFormat()
  const standardRef = useRef<HTMLDetailsElement>(null)
  const optionalRef = useRef<HTMLDetailsElement>(null)

  useEffect(() => {
    if (!expandEquipment) return
    const el = expandEquipment.which === 'standard' ? standardRef.current : optionalRef.current
    if (!el) return
    el.open = true
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [expandEquipment])

  // Recomputed locally (was VehicleDetail.tsx:444) — the Overview reads it for
  // the VIN-decoded / powertrain / non-motorized-fuel-type gates.
  const isMotorized =
    vehicle.vehicle_type &&
    !['Trailer', 'FifthWheel', 'TravelTrailer'].includes(vehicle.vehicle_type)

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return t('detail.notSpecified')
    return formatDateForDisplay(dateString, { year: 'numeric', month: 'long', day: 'numeric' }, dateLocale)
  }

  const formatStickerValue = (raw: unknown): string | null => {
    const text = Array.isArray(raw) ? raw.join(', ') : typeof raw === 'string' ? raw : null
    if (!text) return null
    return /^\d+(\.\d+)?$/.test(text)
      ? formatCurrency(text, { currencyCode, locale, zeroIsValid: true })
      : text
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      {/* Basic Information */}
      <Card breakInside>
        <CardHeader title={t('detail.basicInformation')} />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div><p className="text-sm text-text-mute">{t('edit.year')}</p><p className="font-medium text-text">{vehicle.year || t('detail.notSpecified')}</p></div>
          <div><p className="text-sm text-text-mute">{t('edit.make')}</p><p className="font-medium text-text">{vehicle.make || t('detail.notSpecified')}</p></div>
          <div><p className="text-sm text-text-mute">{t('edit.model')}</p><p className="font-medium text-text">{vehicle.model || t('detail.notSpecified')}</p></div>
          <div><p className="text-sm text-text-mute">{t('detail.misc.exteriorColor')}</p><p className="font-medium text-text">{vehicle.exterior_color || vehicle.color || t('detail.notSpecified')}</p></div>
          {vehicle.interior_color && (
            <div><p className="text-sm text-text-mute">{t('detail.misc.interiorColor')}</p><p className="font-medium text-text">{vehicle.interior_color}</p></div>
          )}
          <div><p className="text-sm text-text-mute">{t('edit.licensePlate')}</p><p className="font-medium text-text">{vehicle.license_plate || t('detail.notSpecified')}</p></div>
          <div><p className="text-sm text-text-mute">{t('wizard.vin')}</p><Mono size="sm" variant="vin" className="block">{vehicle.vin}</Mono></div>
        </div>
      </Card>

      {/* Purchase Information */}
      <Card breakInside>
        <CardHeader title={t('detail.purchaseInformation')} />
        <div className="space-y-3">
          <div>
            <p className="text-sm text-text-mute flex items-center gap-2"><Calendar className="w-4 h-4" /><span>{t('edit.purchaseDate')}</span></p>
            <Mono size="sm" className="mt-1 block">{formatDate(vehicle.purchase_date)}</Mono>
          </div>
          <div>
            <p className="text-sm text-text-mute"><span>{t('edit.purchasePrice')}</span></p>
            <Mono size="sm" className="mt-1 block">{formatCurrency(vehicle.purchase_price, { currencyCode, locale, fallback: t('detail.notSpecified') })}</Mono>
          </div>
        </div>
      </Card>

      {/* Sale Information (if sold) */}
      {vehicle.sold_date && (
        <Card breakInside className="border-warning">
          <CardHeader title={t('detail.saleInformation')} />
          <div className="space-y-3">
            <div>
              <p className="text-sm text-text-mute flex items-center gap-2"><Calendar className="w-4 h-4" /><span>{t('detail.misc.saleDate')}</span></p>
              <Mono size="sm" className="mt-1 block">{formatDate(vehicle.sold_date)}</Mono>
            </div>
            <div>
              <p className="text-sm text-text-mute"><span>{t('detail.misc.salePrice')}</span></p>
              <Mono size="sm" className="mt-1 block">{formatCurrency(vehicle.sold_price, { currencyCode, locale, fallback: t('detail.notSpecified') })}</Mono>
            </div>
          </div>
        </Card>
      )}

      {/* Connected Devices (TorqueSource trigger only — P3-done body) */}
      <Card breakInside>
        <CardHeader title={t('detail.connectedDevices')} />
        <div className="flex items-center justify-between gap-4">
          <p className="text-sm text-text-mute">{t('forms:modal.torque.description')}</p>
          <Button variant="primary" icon={Radio} onClick={() => onOpenModal('torqueSource')} title={t('forms:modal.torque.launchButtonTooltip')}>
            {t('forms:modal.torque.launchButton')}
          </Button>
        </div>
      </Card>

      {/* Last Known Location (Card shell; leaflet body unchanged — hex removal is P6d/P7) */}
      {lastLocation != null && (
        <Card breakInside>
          <CardHeader title={t('detail.lastLocation')} />
          <Suspense fallback={<div className="h-[220px] rounded-panel bg-surface-2 animate-pulse" />}>
            <LastLocationMap latitude={lastLocation.latitude} longitude={lastLocation.longitude} />
          </Suspense>
          <p className="mt-3 text-sm text-text-mute">
            {t('detail.lastLocationSeenAt', { time: formatDateTime(lastLocation.timestamp, timeFormat) })}
          </p>
        </Card>
      )}

      {/* Transfer History (its own file is retokenized in Step 3) */}
      <TransferHistorySection vin={vin} />

      {/* VIN Decoded Information */}
      {(vehicle.trim || vehicle.body_class || vehicle.drive_type || vehicle.doors || vehicle.gvwr_class || vehicle.wheel_specs || vehicle.tire_specs || (!isMotorized && vehicle.fuel_type)) && (
        <Card breakInside>
          <CardHeader title={t('detail.vehicleDetails')} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {vehicle.trim && (<div><p className="text-sm text-text-mute">{t('edit.trim')}</p><p className="font-medium text-text">{vehicle.trim}</p></div>)}
            {vehicle.body_class && (<div><p className="text-sm text-text-mute">{t('edit.bodyClass')}</p><p className="font-medium text-text">{vehicle.body_class}</p></div>)}
            {vehicle.drive_type && (<div><p className="text-sm text-text-mute">{t('edit.driveType')}</p><p className="font-medium text-text">{vehicle.drive_type}</p></div>)}
            {vehicle.doors && (<div><p className="text-sm text-text-mute">{t('edit.doors')}</p><Mono size="sm" className="block">{vehicle.doors}</Mono></div>)}
            {vehicle.gvwr_class && (<div><p className="text-sm text-text-mute">{t('detail.misc.gvwrClass')}</p><p className="font-medium text-text">{vehicle.gvwr_class}</p></div>)}
            {vehicle.wheel_specs && (<div><p className="text-sm text-text-mute">{t('detail.misc.wheels')}</p><Mono size="sm" className="block">{vehicle.wheel_specs}</Mono></div>)}
            {vehicle.tire_specs && (<div><p className="text-sm text-text-mute">{t('detail.misc.tires')}</p><Mono size="sm" className="block">{vehicle.tire_specs}</Mono></div>)}
            {!isMotorized && vehicle.fuel_type && (<div><p className="text-sm text-text-mute">{t('edit.fuelType')}</p><p className="font-medium text-text">{t(`forms:fuel.fuelTypes.${vehicle.fuel_type}`, { defaultValue: vehicle.fuel_type })}</p></div>)}
          </div>
        </Card>
      )}

      {/* Powertrain (motorized only) */}
      {isMotorized && (vehicle.displacement_l || vehicle.cylinders || vehicle.fuel_type || vehicle.sticker_engine_description || vehicle.transmission_type || vehicle.transmission_speeds || vehicle.sticker_transmission_description || vehicle.sticker_drivetrain) && (
        <Card breakInside>
          <CardHeader title={t('detail.powertrain')} />
          <div className="space-y-3">
            {(vehicle.displacement_l || vehicle.cylinders || vehicle.fuel_type || vehicle.sticker_engine_description) && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {vehicle.sticker_engine_description && (<div className="md:col-span-2"><p className="text-sm text-text-mute">{t('detail.misc.engine')}</p><p className="font-medium text-text">{vehicle.sticker_engine_description}</p></div>)}
                {vehicle.displacement_l && (<div><p className="text-sm text-text-mute">{t('detail.misc.displacement')}</p><Mono size="sm" className="block">{t('detail.misc.displacementLiters', { value: vehicle.displacement_l })}</Mono></div>)}
                {vehicle.cylinders && (<div><p className="text-sm text-text-mute">{t('edit.cylinders')}</p><Mono size="sm" className="block">{vehicle.cylinders}</Mono></div>)}
                {vehicle.fuel_type && (<div><p className="text-sm text-text-mute">{t('edit.fuelType')}</p><p className="font-medium text-text">{t(`forms:fuel.fuelTypes.${vehicle.fuel_type}`, { defaultValue: vehicle.fuel_type })}</p></div>)}
              </div>
            )}
            {(vehicle.transmission_type || vehicle.transmission_speeds || vehicle.sticker_transmission_description) && (
              <div className={(vehicle.displacement_l || vehicle.cylinders || vehicle.fuel_type || vehicle.sticker_engine_description) ? 'pt-3 border-t border-border' : ''}>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {vehicle.sticker_transmission_description && (<div className="md:col-span-2"><p className="text-sm text-text-mute">{t('detail.misc.transmission')}</p><p className="font-medium text-text">{vehicle.sticker_transmission_description}</p></div>)}
                  {vehicle.transmission_type && (<div><p className="text-sm text-text-mute">{t('detail.misc.type')}</p><p className="font-medium text-text">{vehicle.transmission_type}</p></div>)}
                  {vehicle.transmission_speeds && (<div><p className="text-sm text-text-mute">{t('detail.misc.speeds')}</p><Mono size="sm" className="block">{vehicle.transmission_speeds}</Mono></div>)}
                  {vehicle.sticker_drivetrain && (<div><p className="text-sm text-text-mute">{t('detail.misc.drivetrain')}</p><p className="font-medium text-text">{vehicle.sticker_drivetrain}</p></div>)}
                </div>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* MSRP & Pricing */}
      {(vehicle.msrp_base || vehicle.msrp_options || vehicle.msrp_total || vehicle.destination_charge) && (
        <Card breakInside>
          <CardHeader title={t('detail.msrpPricing')} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {vehicle.msrp_base && (<div><p className="text-sm text-text-mute">{t('detail.misc.basePrice')}</p><Mono size="sm" className="block">{formatCurrency(vehicle.msrp_base, { currencyCode, locale })}</Mono></div>)}
            {vehicle.msrp_options && (<div><p className="text-sm text-text-mute">{t('detail.misc.options')}</p><Mono size="sm" className="block">{formatCurrency(vehicle.msrp_options, { currencyCode, locale })}</Mono></div>)}
            {vehicle.destination_charge && (<div><p className="text-sm text-text-mute">{t('detail.misc.destination')}</p><Mono size="sm" className="block">{formatCurrency(vehicle.destination_charge, { currencyCode, locale })}</Mono></div>)}
            {vehicle.msrp_total && (<div><p className="text-sm text-text-mute">{t('detail.misc.totalMsrp')}</p><Mono size="lg" weight="semibold" className="block">{formatCurrency(vehicle.msrp_total, { currencyCode, locale })}</Mono></div>)}
          </div>
        </Card>
      )}

      {/* Fuel Economy */}
      {(vehicle.fuel_economy_city_l_per_100km || vehicle.fuel_economy_highway_l_per_100km || vehicle.fuel_economy_combined_l_per_100km) && (
        <Card breakInside>
          <CardHeader title={t('detail.fuelEconomy')} />
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {vehicle.fuel_economy_city_l_per_100km && (<div><p className="text-sm text-text-mute">{t('detail.misc.city')}</p><Mono size="sm" className="block">{UnitFormatter.formatFuelEconomy(parseFloat(vehicle.fuel_economy_city_l_per_100km), unitSystem)}</Mono></div>)}
            {vehicle.fuel_economy_highway_l_per_100km && (<div><p className="text-sm text-text-mute">{t('detail.misc.highway')}</p><Mono size="sm" className="block">{UnitFormatter.formatFuelEconomy(parseFloat(vehicle.fuel_economy_highway_l_per_100km), unitSystem)}</Mono></div>)}
            {vehicle.fuel_economy_combined_l_per_100km && (<div><p className="text-sm text-text-mute">{t('detail.misc.combined')}</p><Mono size="sm" className="block">{UnitFormatter.formatFuelEconomy(parseFloat(vehicle.fuel_economy_combined_l_per_100km), unitSystem)}</Mono></div>)}
          </div>
        </Card>
      )}

      {/* Warranty */}
      {(vehicle.warranty_powertrain || vehicle.warranty_basic) && (
        <Card breakInside>
          <CardHeader title={t('detail.warranty')} />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {vehicle.warranty_basic && (<div><p className="text-sm text-text-mute">{t('detail.misc.basic')}</p><p className="font-medium text-text">{vehicle.warranty_basic}</p></div>)}
            {vehicle.warranty_powertrain && (<div><p className="text-sm text-text-mute">{t('detail.powertrain')}</p><p className="font-medium text-text">{vehicle.warranty_powertrain}</p></div>)}
          </div>
        </Card>
      )}

      {/* Environmental Ratings */}
      {(vehicle.environmental_rating_ghg || vehicle.environmental_rating_smog) && (
        <Card breakInside>
          <CardHeader title={t('detail.environmentalRatings')} />
          <div className="grid grid-cols-2 gap-4">
            {vehicle.environmental_rating_ghg && (<div><p className="text-sm text-text-mute">{t('detail.misc.ghgRating')}</p><p className="font-medium text-text">{vehicle.environmental_rating_ghg}</p></div>)}
            {vehicle.environmental_rating_smog && (<div><p className="text-sm text-text-mute">{t('detail.misc.smogRating')}</p><p className="font-medium text-text">{vehicle.environmental_rating_smog}</p></div>)}
          </div>
        </Card>
      )}

      {/* Assembly Location */}
      {vehicle.assembly_location && (
        <Card breakInside>
          <CardHeader title={t('detail.manufacturing')} />
          <div>
            <p className="text-sm text-text-mute">{t('detail.misc.assemblyLocation')}</p>
            <p className="font-medium text-text">{vehicle.assembly_location}</p>
          </div>
        </Card>
      )}

      {/* Standard Equipment — Collapsible (Task-4 ref + expand effect preserved) */}
      {vehicle.standard_equipment && typeof vehicle.standard_equipment === 'object' && Object.keys(vehicle.standard_equipment).length > 0 && (
        <details ref={standardRef} className="group rounded-card border border-border bg-surface p-6 break-inside-avoid">
          <summary className="cursor-pointer list-none flex items-center justify-between text-xl font-semibold text-text">
            <span>{t('detail.standardEquipment')}</span>
            <span className="text-sm font-normal text-text-mute group-open:rotate-180 transition-transform">▼</span>
          </summary>
          <div className="space-y-3 mt-4">
            {Object.entries(vehicle.standard_equipment).map(([category, items]) => (
              <div key={category}>
                {category !== 'items' && (<p className="text-sm font-medium text-(--accent-fg) mb-2">{category}</p>)}
                {Array.isArray(items) ? (
                  <ul className="list-disc list-inside space-y-1">
                    {items.map((item, idx) => (<li key={idx} className="text-sm text-text">{item}</li>))}
                  </ul>
                ) : (
                  <p className="text-sm text-text">{String(items)}</p>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Optional Equipment with Pricing — Collapsible (Task-4 ref + expand effect preserved) */}
      {vehicle.optional_equipment && typeof vehicle.optional_equipment === 'object' && Object.keys(vehicle.optional_equipment).length > 0 && (
        <details ref={optionalRef} className="group rounded-card border border-border bg-surface p-6 break-inside-avoid">
          <summary className="cursor-pointer list-none flex items-center justify-between text-xl font-semibold text-text">
            <span>{t('detail.optionalEquipment')}</span>
            <span className="text-sm font-normal text-text-mute group-open:rotate-180 transition-transform">▼</span>
          </summary>
          <div className="space-y-2 mt-4">
            {Object.entries(vehicle.optional_equipment).map(([category, items]) => (
              <div key={category}>
                {category !== 'items' && (<p className="text-sm font-medium text-(--accent-fg) mb-2">{category}</p>)}
                {Array.isArray(items) ? (
                  <ul className="space-y-1">
                    {(items as string[]).map((item, idx) => {
                      const price = formatStickerValue(vehicle.window_sticker_options_detail?.[item])
                      return (
                        <li key={idx} className="text-sm text-text flex justify-between">
                          <span>{item}</span>
                          {price && <Mono size="sm" tone="muted">{price}</Mono>}
                        </li>
                      )
                    })}
                  </ul>
                ) : (
                  <p className="text-sm text-text">{String(items)}</p>
                )}
              </div>
            ))}
          </div>
        </details>
      )}

      {/* Packages */}
      {vehicle.window_sticker_packages && typeof vehicle.window_sticker_packages === 'object' && Object.keys(vehicle.window_sticker_packages).length > 0 && (
        <Card breakInside>
          <CardHeader title={t('detail.packages')} />
          <div className="space-y-2">
            {Object.entries(vehicle.window_sticker_packages).map(([packageName, rawValue]) => {
              const value = formatStickerValue(rawValue)
              return (
                <div key={packageName} className="flex justify-between items-center">
                  <span className="text-sm text-text">{packageName}</span>
                  {value && <Mono size="sm" tone="muted">{value}</Mono>}
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {/* Window Sticker — cars/trucks/SUVs only. No OCR Badge (would be new hardcoded
          copy) and no drop-zone (never existed); upload is a single Button. */}
      {vehicle.vehicle_type && ['Car', 'Truck', 'SUV'].includes(vehicle.vehicle_type) && (
        <Card breakInside>
          <CardHeader
            title={t('detail.windowSticker')}
            actions={
              <Link to={`/vehicles/${vin}/window-sticker-test`} className="rounded-control bg-surface-2 px-2 py-1 text-xs text-text-mute hover:text-(--accent-fg) transition-colors">
                {t('detail.misc.testOcr')}
              </Link>
            }
          />
          {vehicle.window_sticker_file_path ? (
            <div className="space-y-3">
              <button onClick={onDownloadWindowSticker} className="w-full cursor-pointer">
                <div className="h-20 rounded-panel border border-border bg-surface-2 overflow-hidden flex items-center justify-center gap-3 hover:bg-surface transition-colors">
                  <FileText className="w-8 h-8 text-(--accent-fg)" />
                  <div className="text-left">
                    <p className="text-sm font-medium text-text">{t('detail.viewWindowSticker')}</p>
                    <p className="text-xs text-text-mute">{t('detail.clickToOpenPDF')}</p>
                  </div>
                </div>
              </button>
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-faint">
                {vehicle.window_sticker_parser_used && (<span>{t('detail.misc.parser', { parser: vehicle.window_sticker_parser_used })}</span>)}
                {vehicle.window_sticker_confidence_score && (<span>{t('detail.misc.confidence', { score: Number(vehicle.window_sticker_confidence_score).toFixed(0) })}</span>)}
                {vehicle.window_sticker_extracted_vin && (
                  <span className={vehicle.window_sticker_extracted_vin === vehicle.vin ? 'text-success' : 'text-warning'}>
                    {vehicle.window_sticker_extracted_vin === vehicle.vin ? `✓ ${t('detail.misc.vinVerified')}` : `⚠ ${t('detail.misc.vinMismatch')}`}
                  </span>
                )}
              </div>
              <button onClick={() => onOpenModal('windowSticker')} className="text-sm text-text-mute hover:text-text transition-colors cursor-pointer">
                {t('detail.replaceSticker')}
              </button>
            </div>
          ) : (
            <div className="text-center py-4">
              <FileText className="w-10 h-10 text-text-mute mx-auto mb-2 opacity-50" />
              <p className="text-sm text-text-mute mb-3">{t('detail.noWindowSticker')}</p>
              <Button variant="primary" size="sm" onClick={() => onOpenModal('windowSticker')}>
                {t('detail.uploadWindowSticker')}
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
