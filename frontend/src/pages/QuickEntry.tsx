import { useState, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { Car, Fuel, Flame, Droplets, Wrench, Gauge, ChevronRight, LayoutDashboard, Timer } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'
import FuelRecordForm from '../components/FuelRecordForm'
import PropaneRecordForm from '../components/PropaneRecordForm'
import DEFRecordForm from '../components/DEFRecordForm'
import ServiceVisitForm from '../components/ServiceVisitForm'
import OdometerRecordForm from '../components/OdometerRecordForm'
import HoursRecordForm from '../components/HoursRecordForm'
import { Select } from '../components/ui'
import { useQuickEntryVehicles } from '../hooks/queries/useQuickEntryVehicles'
import { vehicleLabel } from '../utils/vehicleLabel'
import { withBase } from '../utils/basePath'
import { fillUpKind, vehicleLogKinds } from '../utils/vehicleLogKinds'
import { VehicleUnitScope } from '../contexts/VehicleUnitScope'

type EntryType = 'fuel' | 'def' | 'propane' | 'service' | 'odometer' | 'hours' | null

interface Action {
  type: Exclude<EntryType, null>
  offered: boolean
  icon: LucideIcon
  tint: string
  title: string
  description: string
}

export default function QuickEntry() {
  const { t } = useTranslation('vehicles')
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const [selectedVin, setSelectedVin] = useState<string>('')
  const [entryType, setEntryType] = useState<EntryType>(null)

  // Fetched via TanStack Query so a transient failure retries and refetches on
  // focus instead of leaving a permanent empty screen (#114).
  const { data: vehicles = [], isLoading, isError, isFetching, refetch } = useQuickEntryVehicles()

  // Set user-scoped session flag so returning to "/" renders Dashboard, not another redirect
  useEffect(() => {
    if (user?.id) {
      sessionStorage.setItem(`qe_redirected:${user.id}`, '1')
    }
  }, [user?.id])

  // Deep links / PWA shortcuts: /quick-entry?action=add-fuel|add-service|odometer&vin=...
  useEffect(() => {
    const action = (searchParams.get('action') || '').toLowerCase()
    const vinParam = (searchParams.get('vin') || '').toUpperCase()
    if (vinParam) {
      setSelectedVin(vinParam)
    }
    if (action === 'add-fuel' || action === 'fuel') {
      setEntryType('fuel')
    } else if (action === 'add-service' || action === 'service') {
      setEntryType('service')
    } else if (action === 'odometer' || action === 'add-odometer') {
      setEntryType('odometer')
    } else if (action === 'hours' || action === 'add-hours' || action === 'engine-hours') {
      setEntryType('hours')
    }
  }, [searchParams])

  // Auto-select when the account has exactly one vehicle, without clobbering a
  // selection the user already made.
  useEffect(() => {
    if (vehicles.length === 1) {
      setSelectedVin((prev) => prev || vehicles[0].vin)
    }
  }, [vehicles])

  const selectedVehicle = vehicles.find(v => v.vin === selectedVin)
  // The vehicle page's rule, so a fifth wheel offers propane here as it does
  // there, and no fuel or mileage.
  const kinds = vehicleLogKinds(selectedVehicle)

  // What actually opens. A deep link names an entry before the vehicles load
  // and whatever the vehicle is, so it is resolved here: "add fuel" is the
  // vehicle's own fill-up (propane on a fifth wheel), and an entry the vehicle
  // does not log opens nothing.
  const openEntry: EntryType =
    !selectedVehicle || entryType === null
      ? null
      : entryType === 'fuel'
        ? fillUpKind(kinds)
        : entryType === 'service' || kinds[entryType]
          ? entryType
          : null

  // In the vehicle page's order: fill-ups (fuel, DEF, propane), then service,
  // then usage.
  const actions: Action[] = [
    { type: 'fuel', offered: kinds.fuel, icon: Fuel, tint: 'text-blue-500 bg-blue-500/10', title: t('quickEntry.fuelUp'), description: t('quickEntry.fuelUpDesc') },
    { type: 'def', offered: kinds.def, icon: Droplets, tint: 'text-sky-500 bg-sky-500/10', title: t('quickEntry.def'), description: t('quickEntry.defDesc') },
    { type: 'propane', offered: kinds.propane, icon: Flame, tint: 'text-amber-500 bg-amber-500/10', title: t('quickEntry.propane'), description: t('quickEntry.propaneDesc') },
    { type: 'service', offered: true, icon: Wrench, tint: 'text-orange-500 bg-orange-500/10', title: t('quickEntry.serviceVisit'), description: t('quickEntry.serviceVisitDesc') },
    { type: 'odometer', offered: kinds.odometer, icon: Gauge, tint: 'text-green-500 bg-green-500/10', title: t('quickEntry.mileage'), description: t('quickEntry.mileageDesc') },
    { type: 'hours', offered: kinds.hours, icon: Timer, tint: 'text-teal-500 bg-teal-500/10', title: t('quickEntry.engineHours'), description: t('quickEntry.engineHoursDesc') },
  ]

  const handleSuccess = (type: EntryType) => {
    const labels: Record<string, string> = {
      fuel: t('quickEntry.fuelRecord'),
      def: t('quickEntry.defRecord'),
      propane: t('quickEntry.propaneRecord'),
      service: t('quickEntry.serviceVisit'),
      odometer: t('quickEntry.mileage'),
      hours: t('quickEntry.engineHours'),
    }
    toast.success(t('quickEntry.recordSaved', { type: labels[type as string] ?? t('quickEntry.record') }))
    setEntryType(null)
  }

  return (
    <div className="min-h-screen bg-garage-bg flex flex-col">
      {/* Minimal header */}
      <header className="bg-garage-surface border-b border-garage-border px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Car className="w-5 h-5 text-(--accent-fg)" />
          <span className="font-semibold text-garage-text">{t('common:appName')}</span>
        </div>
        <Link
          to="/"
          className="flex items-center gap-1 text-sm text-(--accent-fg) hover:underline"
        >
          <LayoutDashboard className="w-4 h-4" />
          {t('common:dashboard')}
        </Link>
      </header>

      <main className="flex-1 px-4 py-6 max-w-lg mx-auto w-full">
        <h1 className="text-xl font-bold text-garage-text mb-6">{t('quickEntry.title')}</h1>

        {isLoading && (
          <div className="text-garage-text-muted text-center py-12">{t('quickEntry.loadingVehicles')}</div>
        )}

        {!isLoading && isError && (
          <div className="text-center py-12">
            <p className="text-danger-500 mb-4">{t('quickEntry.loadError')}</p>
            <button
              onClick={() => void refetch()}
              disabled={isFetching}
              className="text-(--accent-fg) hover:underline disabled:opacity-50"
            >
              {isFetching ? t('quickEntry.loadingVehicles') : t('quickEntry.retry')}
            </button>
          </div>
        )}

        {!isLoading && !isError && vehicles.length === 0 && (
          <div className="text-center py-12">
            <p className="text-garage-text-muted mb-4">{t('quickEntry.noVehicles')}</p>
            <Link to="/" className="text-(--accent-fg) hover:underline">
              {t('quickEntry.goToDashboard')}
            </Link>
          </div>
        )}

        {!isLoading && !isError && vehicles.length > 0 && (
          <div className="space-y-6">
            {/* Vehicle selector */}
            <div>
              <label className="block text-sm font-medium text-garage-text mb-2">
                {t('quickEntry.vehicle')}
              </label>
              {vehicles.length === 1 ? (
                /* Single vehicle — show as a card, not a dropdown */
                <div className="flex items-center gap-3 p-3 bg-garage-surface rounded-lg border border-garage-border">
                  {selectedVehicle?.thumbnail_url ? (
                    <img
                      src={withBase(selectedVehicle.thumbnail_url)}
                      alt={selectedVehicle.nickname}
                      className="w-12 h-12 rounded object-cover flex-shrink-0"
                    />
                  ) : (
                    <div className="w-12 h-12 rounded bg-garage-bg flex items-center justify-center flex-shrink-0">
                      <Car className="w-6 h-6 text-garage-text-muted" />
                    </div>
                  )}
                  <span className="font-medium text-garage-text">{vehicleLabel(vehicles[0])}</span>
                </div>
              ) : (
                <Select
                  value={selectedVin}
                  onChange={e => setSelectedVin(e.target.value)}
                  placeholder={t('quickEntry.selectVehicle')}
                  options={vehicles.map(v => ({ value: v.vin, label: vehicleLabel(v) }))}
                />
              )}
            </div>

            {/* Action buttons — only shown once a vehicle is selected */}
            {selectedVin && (
              <div>
                <p className="text-sm font-medium text-garage-text mb-3">{t('quickEntry.whatLogging')}</p>
                <div className="grid grid-cols-1 gap-3">
                  {actions.filter((action) => action.offered).map(({ type, icon: Icon, tint, title, description }) => (
                    <button
                      key={type}
                      onClick={() => setEntryType(type)}
                      className="flex items-center justify-between w-full px-4 py-4 bg-garage-surface border border-garage-border rounded-lg text-left hover:border-primary transition-colors active:scale-95"
                    >
                      <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-lg ${tint}`}>
                          <Icon className="w-5 h-5" />
                        </div>
                        <div>
                          <div className="font-medium text-garage-text">{title}</div>
                          <div className="text-xs text-garage-text-muted">{description}</div>
                        </div>
                      </div>
                      <ChevronRight className="w-5 h-5 text-garage-text-muted" />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </main>

      {/* Modal forms, opened by the action buttons. Each form pins the
          vehicle's odometer unit and the account set itself when it mounts
          (R4), so this scope stays live. The key remounts the form if a deep
          link swaps the vehicle under it. */}
      {openEntry !== null && selectedVehicle && (
        <VehicleUnitScope key={`${openEntry}:${selectedVin}`} distanceUnit={selectedVehicle.distance_unit}>
          {openEntry === 'fuel' && (
            <FuelRecordForm
              vin={selectedVin}
              onClose={() => setEntryType(null)}
              onSuccess={() => handleSuccess('fuel')}
            />
          )}

          {openEntry === 'def' && (
            <DEFRecordForm
              vin={selectedVin}
              onClose={() => setEntryType(null)}
              onSuccess={() => handleSuccess('def')}
            />
          )}

          {openEntry === 'propane' && (
            <PropaneRecordForm
              vin={selectedVin}
              onClose={() => setEntryType(null)}
              onSuccess={() => handleSuccess('propane')}
            />
          )}

          {openEntry === 'service' && (
            <ServiceVisitForm
              vin={selectedVin}
              vehicleType={selectedVehicle?.vehicle_type}
              onClose={() => setEntryType(null)}
              onSuccess={() => handleSuccess('service')}
            />
          )}

          {openEntry === 'odometer' && (
            <OdometerRecordForm
              vin={selectedVin}
              onClose={() => setEntryType(null)}
              onSuccess={() => handleSuccess('odometer')}
            />
          )}

          {openEntry === 'hours' && (
            <HoursRecordForm
              vin={selectedVin}
              onClose={() => setEntryType(null)}
              onSuccess={() => handleSuccess('hours')}
            />
          )}
        </VehicleUnitScope>
      )}
    </div>
  )
}
