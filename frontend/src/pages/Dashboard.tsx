import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus, Car as CarIcon, RefreshCw, ChevronDown, AlertCircle, Users, Archive, CheckSquare } from 'lucide-react'
import VehicleStatisticsCard from '../components/VehicleStatisticsCard'
import ExternalVehicleCard from '../components/ExternalVehicleCard'
import ExternalVehicleModal from '../components/modals/ExternalVehicleModal'
import BulkArchiveModal from '../components/modals/BulkArchiveModal'
import VehicleWizard from '../components/VehicleWizard'
import FleetHealthStrip from '../components/FleetHealthStrip'
import { PageHeader, Dropdown, Button, EmptyState, Card } from '../components/ui'
import type { DropdownItem } from '../components/ui'
import type { DashboardResponse, VehicleStatistics } from '../types/dashboard'
import type { ExternalVehicle, ExternalVehicleKind } from '../types/externalVehicle'
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

export default function Dashboard() {
  const { t } = useTranslation('vehicles')
  const location = useLocation()
  const navigate = useNavigate()
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [externalVehicles, setExternalVehicles] = useState<ExternalVehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showWizard, setShowWizard] = useState(false)
  const [sortBy, setSortBy] = useState<SortOption>('name')
  const [modalKind, setModalKind] = useState<ExternalVehicleKind | null>(null)
  const [editingExternal, setEditingExternal] = useState<ExternalVehicle | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedVins, setSelectedVins] = useState<Set<string>>(new Set())
  const [showBulkArchive, setShowBulkArchive] = useState(false)

  const tRef = useRef(t)
  useEffect(() => {
    tRef.current = t
  }, [t])

  const loadDashboard = useCallback(async () => {
    setError(null)
    try {
      const [dashRes, extRes] = await Promise.all([
        api.get('/dashboard'),
        listExternalVehicles().catch(() => ({ vehicles: [], total: 0 })),
      ])
      setDashboard(dashRes.data)
      setExternalVehicles(extRes.vehicles)
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
    () => externalVehicles.filter((v) => v.kind === 'reference'),
    [externalVehicles],
  )
  const customerVehicles = useMemo(
    () => externalVehicles.filter((v) => v.kind === 'customer'),
    [externalVehicles],
  )

  const hasSharedVehicles = sharedVehicles.length > 0
  const familyItemCount = sharedVehicles.length + referenceVehicles.length
  const showFamilyEmpty = familyItemCount === 0 && ownedVehicles.length > 0
  const showFamilySection = familyItemCount > 0 || showFamilyEmpty
  const showCustomersSection = customerVehicles.length > 0 || ownedVehicles.length > 0

  const vehicleCount = dashboard?.total_vehicles || 0
  const hasAnyContent =
    vehicleCount > 0 || externalVehicles.length > 0

  const sortItems: DropdownItem[] = [
    { id: 'name', label: t('dashboard.sortByName'), checked: sortBy === 'name', onSelect: () => setSortBy('name') },
    { id: 'year-new', label: t('dashboard.newestFirst'), checked: sortBy === 'year-new', onSelect: () => setSortBy('year-new') },
    { id: 'year-old', label: t('dashboard.oldestFirst'), checked: sortBy === 'year-old', onSelect: () => setSortBy('year-old') },
    { id: 'maintenance', label: t('dashboard.byMaintenance'), checked: sortBy === 'maintenance', onSelect: () => setSortBy('maintenance') },
  ]
  const sortLabel = sortItems.find((i) => i.checked)?.label ?? ''

  const openExternalModal = (kind: ExternalVehicleKind, vehicle?: ExternalVehicle) => {
    setModalKind(kind)
    setEditingExternal(vehicle ?? null)
  }

  const closeExternalModal = () => {
    setModalKind(null)
    setEditingExternal(null)
  }

  const toggleSelectMode = () => {
    setSelectMode((prev) => {
      if (prev) setSelectedVins(new Set())
      return !prev
    })
  }

  const toggleVin = (vin: string) => {
    setSelectedVins((prev) => {
      const next = new Set(prev)
      if (next.has(vin)) next.delete(vin)
      else next.add(vin)
      return next
    })
  }

  return (
    <>
      <div className="container mx-auto px-4 py-8">
        <PageHeader
          title={t('dashboard.title')}
          actions={
            <>
              {vehicleCount > 0 && (
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
              {ownedVehicles.length > 1 && (
                <Button
                  variant="secondary"
                  icon={selectMode ? CheckSquare : Archive}
                  onClick={toggleSelectMode}
                >
                  {selectMode ? t('dashboard.cancelSelect') : t('dashboard.selectVehicles')}
                </Button>
              )}
              {selectMode && selectedVins.size > 0 && (
                <Button variant="primary" icon={Archive} onClick={() => setShowBulkArchive(true)}>
                  {t('dashboard.bulkArchive')} ({selectedVins.size})
                </Button>
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
            {dashboard.fleet_health && ownedVehicles.length + sharedVehicles.length > 0 ? (
              <FleetHealthStrip fleet={dashboard.fleet_health} />
            ) : null}

            <section>
              <h2 className="mb-4 text-lg font-semibold tracking-[-0.01em] text-text">
                {t('dashboard.myVehiclesSection', { count: ownedVehicles.length })}
              </h2>
              {ownedVehicles.length > 0 ? (
                <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[22px]">
                  {ownedVehicles.map((vehicleStats) => (
                    <VehicleStatisticsCard
                      key={vehicleStats.vin}
                      stats={vehicleStats}
                      selectMode={selectMode}
                      selected={selectedVins.has(vehicleStats.vin)}
                      onToggleSelect={toggleVin}
                    />
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

            {showFamilySection ? (
              <section>
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold tracking-[-0.01em] text-text">
                      {t('dashboard.familyFriendsSection', {
                        count: sharedVehicles.length + referenceVehicles.length,
                      })}
                    </h2>
                    <p className="mt-1 text-sm text-text-mute">{t('dashboard.familyFriendsSubtitle')}</p>
                  </div>
                  <Button variant="secondary" icon={Plus} onClick={() => openExternalModal('reference')}>
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
                        <Button variant="secondary" onClick={() => navigate('/settings')}>
                          {t('dashboard.openSettings')}
                        </Button>
                      }
                    />
                  </Card>
                ) : (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[22px]">
                    {sharedVehicles.map((vehicleStats) => (
                      <VehicleStatisticsCard key={vehicleStats.vin} stats={vehicleStats} />
                    ))}
                    {referenceVehicles.map((vehicle) => (
                      <ExternalVehicleCard
                        key={`ref-${vehicle.id}`}
                        vehicle={vehicle}
                        onClick={() => openExternalModal('reference', vehicle)}
                      />
                    ))}
                  </div>
                )}
              </section>
            ) : null}

            {showCustomersSection || ownedVehicles.length > 0 ? (
              <section>
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 className="text-lg font-semibold tracking-[-0.01em] text-text">
                      {t('dashboard.customersSection', { count: customerVehicles.length })}
                    </h2>
                    <p className="mt-1 text-sm text-text-mute">{t('dashboard.customersSubtitle')}</p>
                  </div>
                  <Button variant="secondary" icon={Plus} onClick={() => openExternalModal('customer')}>
                    {t('dashboard.addCustomerVehicle')}
                  </Button>
                </div>
                {customerVehicles.length > 0 ? (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(340px,1fr))] gap-[22px]">
                    {customerVehicles.map((vehicle) => (
                      <ExternalVehicleCard
                        key={`cust-${vehicle.id}`}
                        vehicle={vehicle}
                        onClick={() => openExternalModal('customer', vehicle)}
                      />
                    ))}
                  </div>
                ) : (
                  <Card padding="none">
                    <EmptyState
                      icon={Users}
                      title={t('dashboard.customersEmptyTitle')}
                      description={t('dashboard.customersEmptyDesc')}
                      action={
                        <Button variant="secondary" icon={Plus} onClick={() => openExternalModal('customer')}>
                          {t('dashboard.addCustomerVehicle')}
                        </Button>
                      }
                    />
                  </Card>
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

      {modalKind && (
        <ExternalVehicleModal
          isOpen
          onClose={closeExternalModal}
          kind={modalKind}
          vehicle={editingExternal}
          onSaved={loadDashboard}
        />
      )}

      <BulkArchiveModal
        isOpen={showBulkArchive}
        vins={Array.from(selectedVins)}
        onClose={() => setShowBulkArchive(false)}
        onConfirm={() => {
          setSelectMode(false)
          setSelectedVins(new Set())
          void loadDashboard()
        }}
      />
    </>
  )
}
