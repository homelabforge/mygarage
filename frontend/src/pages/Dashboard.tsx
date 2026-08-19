import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus, Car as CarIcon, RefreshCw, ChevronDown, AlertCircle, Users } from 'lucide-react'
import VehicleStatisticsCard from '../components/VehicleStatisticsCard'
import ExternalVehicleCard from '../components/ExternalVehicleCard'
import ExternalVehicleModal from '../components/modals/ExternalVehicleModal'
import VehicleWizard from '../components/VehicleWizard'
import FleetHealthStrip from '../components/FleetHealthStrip'
import { PageHeader, Dropdown, Button, EmptyState, Card } from '../components/ui'
import type { DropdownItem } from '../components/ui'
import type { DashboardResponse, VehicleStatistics } from '../types/dashboard'
import type { ExternalVehicle } from '../types/externalVehicle'
import { listExternalVehicles } from '../services/externalVehicleService'
import api from '../services/api'

type SortOption = 'name' | 'year-new' | 'year-old' | 'maintenance'

function sortVehicles(vehicles: VehicleStatistics[], sortBy: SortOption): VehicleStatistics[] {
  return [...vehicles].sort((a, b) => {
    switch (sortBy) {
      case 'name':
        return `${a.year} ${a.make} ${a.model}`.localeCompare(`${b.year} ${b.make} ${b.model}`)
      case 'year-new':
        return (b.year ?? 0) - (a.year ?? 0)
      case 'year-old':
        return (a.year ?? 0) - (b.year ?? 0)
      case 'maintenance':
        if (b.overdue_maintenance_count !== a.overdue_maintenance_count) {
          return b.overdue_maintenance_count - a.overdue_maintenance_count
        }
        return b.upcoming_maintenance_count - a.upcoming_maintenance_count
      default:
        return 0
    }
  })
}

function settingEnabled(
  settings: { key: string; value: string | null }[],
  key: string,
): boolean {
  const row = settings.find((s) => s.key === key)
  return (row?.value || 'false').toLowerCase() === 'true'
}

export default function Dashboard() {
  const { t } = useTranslation('vehicles')
  const location = useLocation()
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [externalVehicles, setExternalVehicles] = useState<ExternalVehicle[]>([])
  const [familyFriendsEnabled, setFamilyFriendsEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showWizard, setShowWizard] = useState(false)
  const [sortBy, setSortBy] = useState<SortOption>('name')
  const [showExternalModal, setShowExternalModal] = useState(false)
  const [editingExternal, setEditingExternal] = useState<ExternalVehicle | null>(null)

  const tRef = useRef(t)
  useEffect(() => {
    tRef.current = t
  }, [t])

  const loadDashboard = useCallback(async () => {
    setError(null)
    try {
      const [dashRes, settingsRes] = await Promise.all([
        api.get('/dashboard'),
        api.get('/settings/public').catch(() => ({ data: { settings: [] } })),
      ])
      const settings: { key: string; value: string | null }[] =
        settingsRes.data?.settings ?? []
      const ffEnabled = settingEnabled(settings, 'family_friends_enabled')
      setFamilyFriendsEnabled(ffEnabled)

      let extVehicles: ExternalVehicle[] = []
      if (ffEnabled) {
        const extRes = await listExternalVehicles().catch(() => ({
          vehicles: [] as ExternalVehicle[],
          total: 0,
        }))
        extVehicles = extRes.vehicles
      }

      setDashboard(dashRes.data)
      setExternalVehicles(extVehicles)
    } catch {
      setError(tRef.current('dashboard.loadError'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDashboard()
  }, [location.key, loadDashboard])

  const handleVehicleCreated = () => {
    loadDashboard()
  }

  const ownedVehicles = useMemo(() => {
    if (!dashboard?.vehicles) return []
    return sortVehicles(
      dashboard.vehicles.filter((v) => !v.is_shared_with_me),
      sortBy,
    )
  }, [dashboard?.vehicles, sortBy])

  const sharedVehicles = useMemo(() => {
    if (!dashboard?.vehicles) return []
    return sortVehicles(
      dashboard.vehicles.filter((v) => v.is_shared_with_me),
      sortBy,
    )
  }, [dashboard?.vehicles, sortBy])

  const referenceVehicles = useMemo(
    () => (familyFriendsEnabled ? externalVehicles : []),
    [externalVehicles, familyFriendsEnabled],
  )

  const showFamilyEmpty =
    familyFriendsEnabled &&
    referenceVehicles.length === 0 &&
    (ownedVehicles.length > 0 || sharedVehicles.length > 0)
  const showFamilySection = familyFriendsEnabled && (referenceVehicles.length > 0 || showFamilyEmpty)
  const showSharedSection = sharedVehicles.length > 0

  const ownedCount = ownedVehicles.length
  const hasAnyContent =
    ownedCount > 0 || sharedVehicles.length > 0 || referenceVehicles.length > 0

  const sortItems: DropdownItem[] = [
    { id: 'name', label: t('dashboard.sortByName'), checked: sortBy === 'name', onSelect: () => setSortBy('name') },
    { id: 'year-new', label: t('dashboard.newestFirst'), checked: sortBy === 'year-new', onSelect: () => setSortBy('year-new') },
    { id: 'year-old', label: t('dashboard.oldestFirst'), checked: sortBy === 'year-old', onSelect: () => setSortBy('year-old') },
    { id: 'maintenance', label: t('dashboard.byMaintenance'), checked: sortBy === 'maintenance', onSelect: () => setSortBy('maintenance') },
  ]
  const sortLabel = sortItems.find((i) => i.checked)?.label ?? ''

  const openExternalModal = (vehicle?: ExternalVehicle) => {
    setEditingExternal(vehicle ?? null)
    setShowExternalModal(true)
  }

  const closeExternalModal = () => {
    setShowExternalModal(false)
    setEditingExternal(null)
  }

  const showSort = ownedCount > 0 || sharedVehicles.length > 0

  return (
    <>
      <div className="container mx-auto px-4 py-8">
        <PageHeader
          title={t('dashboard.title')}
          actions={
            <>
              {showSort && (
                <Dropdown
                  label={t('dashboard.sortVehicles')}
                  align="right"
                  items={sortItems}
                  trigger={
                    <>
                      {t('dashboard.sortTrigger', { label: sortLabel })}
                      <ChevronDown aria-hidden="true" className="h-4 w-4" />
                    </>
                  }
                />
              )}
              <Button variant="primary" icon={Plus} onClick={() => setShowWizard(true)}>
                {t('dashboard.addVehicle')}
              </Button>
            </>
          }
        />

        {loading ? (
          <div className="flex items-center justify-center py-16" role="status" aria-label={t('dashboard.loading')}>
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-[color:var(--accent-solid)] border-t-transparent" />
            <span className="sr-only">{t('dashboard.loading')}</span>
          </div>
        ) : error ? (
          <Card padding="none">
            <EmptyState
              icon={AlertCircle}
              title={error}
              action={
                <Button variant="secondary" icon={RefreshCw} onClick={loadDashboard}>
                  {t('common:retry')}
                </Button>
              }
            />
          </Card>
        ) : dashboard && hasAnyContent ? (
          <div className="space-y-10">
            {dashboard.fleet_health &&
            ownedVehicles.length + sharedVehicles.length > 0 ? (
              <FleetHealthStrip fleet={dashboard.fleet_health} />
            ) : null}

            <section>
              <h2 className="mb-4 text-lg font-semibold tracking-[-0.01em] text-text">
                {t('dashboard.myVehiclesSection', { count: ownedVehicles.length })}
              </h2>
              {ownedVehicles.length > 0 ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[22px]">
                  {ownedVehicles.map((vehicleStats) => (
                    <VehicleStatisticsCard key={vehicleStats.vin} stats={vehicleStats} />
                  ))}
                </div>
              ) : (
                <Card padding="none">
                  <EmptyState
                    icon={CarIcon}
                    title={t('dashboard.noOwnedVehicles')}
                    description={t('dashboard.noOwnedVehiclesDesc')}
                    action={
                      <Button variant="primary" icon={Plus} onClick={() => setShowWizard(true)}>
                        {t('dashboard.addVehicle')}
                      </Button>
                    }
                  />
                </Card>
              )}
            </section>

            {showSharedSection ? (
              <section>
                <h2 className="mb-4 text-lg font-semibold tracking-[-0.01em] text-text">
                  {t('dashboard.sharedWithMeSection', { count: sharedVehicles.length })}
                </h2>
                <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[22px]">
                  {sharedVehicles.map((vehicleStats) => (
                    <VehicleStatisticsCard key={vehicleStats.vin} stats={vehicleStats} />
                  ))}
                </div>
              </section>
            ) : null}

            {showFamilySection ? (
              <section>
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold tracking-[-0.01em] text-text">
                      {t('dashboard.familyFriendsSection', {
                        count: referenceVehicles.length,
                      })}
                    </h2>
                    <p className="mt-1 text-sm text-text-mute">{t('dashboard.familyFriendsSubtitle')}</p>
                  </div>
                  <Button variant="secondary" icon={Plus} onClick={() => openExternalModal()}>
                    {t('dashboard.addReferenceVehicle')}
                  </Button>
                </div>

                {showFamilyEmpty ? (
                  <Card padding="none">
                    <EmptyState
                      icon={Users}
                      title={t('dashboard.familyEmptyTitle')}
                      description={t('dashboard.familyEmptyDesc')}
                      action={
                        <Button variant="secondary" icon={Plus} onClick={() => openExternalModal()}>
                          {t('dashboard.addReferenceVehicle')}
                        </Button>
                      }
                    />
                  </Card>
                ) : (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[22px]">
                    {referenceVehicles.map((vehicle) => (
                      <ExternalVehicleCard
                        key={`ref-${vehicle.id}`}
                        vehicle={vehicle}
                        onClick={() => openExternalModal(vehicle)}
                      />
                    ))}
                  </div>
                )}
              </section>
            ) : null}
          </div>
        ) : (
          <Card padding="none">
            <EmptyState
              icon={CarIcon}
              title={t('dashboard.noVehiclesYet')}
              description={t('dashboard.getStarted')}
              action={
                <Button variant="primary" icon={Plus} onClick={() => setShowWizard(true)}>
                  {t('dashboard.addFirstVehicle')}
                </Button>
              }
            />
          </Card>
        )}
      </div>

      {showWizard && (
        <VehicleWizard
          onClose={() => setShowWizard(false)}
          onSuccess={handleVehicleCreated}
        />
      )}

      {showExternalModal && (
        <ExternalVehicleModal
          isOpen
          onClose={closeExternalModal}
          vehicle={editingExternal}
          onSaved={loadDashboard}
        />
      )}
    </>
  )
}
