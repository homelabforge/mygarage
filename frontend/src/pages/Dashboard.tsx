import { useState, useEffect, useMemo, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Plus, Car as CarIcon, SlidersHorizontal, Filter, RefreshCw } from 'lucide-react'
import VehicleStatisticsCard from '../components/VehicleStatisticsCard'
import VehicleWizard from '../components/VehicleWizard'
import type { DashboardResponse } from '../types/dashboard'
import api from '../services/api'

type SortOption = 'name' | 'year-new' | 'year-old' | 'maintenance'
type FilterOption = 'all' | 'owned' | 'shared'

export default function Dashboard() {
  const { t } = useTranslation('vehicles')
  const location = useLocation()
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showWizard, setShowWizard] = useState(false)
  const [sortBy, setSortBy] = useState<SortOption>('name')
  const [filterBy, setFilterBy] = useState<FilterOption>('all')

  const loadDashboard = useCallback(async () => {
    setError(null)
    try {
      const response = await api.get('/dashboard')
      setDashboard(response.data)
    } catch {
      setError(t('dashboard.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => {
    // Load dashboard data when component mounts or navigation occurs
    loadDashboard()
  }, [location.key, loadDashboard])

  const handleVehicleCreated = () => {
    loadDashboard()
  }

  // Check if there are any shared vehicles
  const hasSharedVehicles = useMemo(() => {
    return dashboard?.vehicles?.some((v) => v.is_shared_with_me) ?? false
  }, [dashboard?.vehicles])

  // Filter and sort vehicles
  const sortedVehicles = useMemo(() => {
    if (!dashboard?.vehicles) return []

    // Apply filter first
    let filtered = dashboard.vehicles
    if (filterBy === 'owned') {
      filtered = dashboard.vehicles.filter((v) => !v.is_shared_with_me)
    } else if (filterBy === 'shared') {
      filtered = dashboard.vehicles.filter((v) => v.is_shared_with_me)
    }

    // Apply sorting
    const sorted = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'name':
          return `${a.year} ${a.make} ${a.model}`.localeCompare(
            `${b.year} ${b.make} ${b.model}`
          )
        case 'year-new':
          return (b.year ?? 0) - (a.year ?? 0)
        case 'year-old':
          return (a.year ?? 0) - (b.year ?? 0)
        case 'maintenance':
          // Sort by overdue count (desc), then upcoming count (desc)
          if (b.overdue_maintenance_count !== a.overdue_maintenance_count) {
            return b.overdue_maintenance_count - a.overdue_maintenance_count
          }
          return b.upcoming_maintenance_count - a.upcoming_maintenance_count
        default:
          return 0
      }
    })

    return sorted
  }, [dashboard?.vehicles, sortBy, filterBy])

  const vehicleCount = dashboard?.total_vehicles || 0

  return (
    <>
      <div className="container mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold mb-2 text-garage-text">{t('dashboard.title')}</h1>
            <p className="text-garage-text-muted">
              {vehicleCount > 0
                ? t('dashboard.managingCount', { count: vehicleCount })
                : t('dashboard.subtitle')}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Filter - only show if there are shared vehicles */}
            {vehicleCount > 0 && hasSharedVehicles && (
              <div className="relative">
                <select
                  value={filterBy}
                  onChange={(e) => setFilterBy(e.target.value as FilterOption)}
                  aria-label={t('dashboard.filterVehicles')}
                  className="pl-3 pr-10 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text appearance-none cursor-pointer"
                >
                  <option value="all" className="bg-garage-bg text-garage-text">
                    {t('dashboard.allVehicles')}
                  </option>
                  <option value="owned" className="bg-garage-bg text-garage-text">
                    {t('dashboard.myVehicles')}
                  </option>
                  <option value="shared" className="bg-garage-bg text-garage-text">
                    {t('dashboard.sharedWithMe')}
                  </option>
                </select>
                <Filter className="absolute right-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted pointer-events-none" />
              </div>
            )}
            {/* Sort */}
            {vehicleCount > 0 && (
              <div className="relative">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value as SortOption)}
                  aria-label={t('dashboard.sortVehicles')}
                  className="pl-3 pr-10 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text appearance-none cursor-pointer"
                >
                  <option value="name" className="bg-garage-bg text-garage-text">
                    {t('dashboard.sortByName')}
                  </option>
                  <option value="year-new" className="bg-garage-bg text-garage-text">
                    {t('dashboard.newestFirst')}
                  </option>
                  <option value="year-old" className="bg-garage-bg text-garage-text">
                    {t('dashboard.oldestFirst')}
                  </option>
                  <option value="maintenance" className="bg-garage-bg text-garage-text">
                    {t('dashboard.byMaintenance')}
                  </option>
                </select>
                <SlidersHorizontal className="absolute right-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-garage-text-muted pointer-events-none" />
              </div>
            )}
            <button
              onClick={() => setShowWizard(true)}
              className="flex items-center gap-2 px-5 py-3 btn btn-primary rounded-lg"
            >
              <Plus className="w-5 h-5" />
              <span>{t('dashboard.addVehicle')}</span>
            </button>
          </div>
        </div>

        {/* Vehicles Grid */}
        {loading ? (
          <div className="flex items-center justify-center py-16" role="status" aria-label={t('dashboard.loading')}>
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
            <span className="sr-only">{t('dashboard.loading')}</span>
          </div>
        ) : error ? (
          <div className="bg-garage-surface rounded-lg border border-garage-border text-center py-16">
            <p className="text-red-500 mb-4">{error}</p>
            <button
              onClick={loadDashboard}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg"
            >
              <RefreshCw className="w-4 h-4" />
              <span>{t('common:retry')}</span>
            </button>
          </div>
        ) : dashboard && vehicleCount > 0 ? (
          <div>

            {/* Vehicles Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {sortedVehicles.map((vehicleStats) => (
                <VehicleStatisticsCard key={vehicleStats.vin} stats={vehicleStats} />
              ))}
            </div>
          </div>
        ) : (
          <div className="bg-garage-surface rounded-lg border border-garage-border text-center py-16">
            <CarIcon className="w-16 h-16 text-garage-text-muted mx-auto mb-4 opacity-50" />
            <h3 className="text-xl font-semibold mb-2 text-garage-text">{t('dashboard.noVehiclesYet')}</h3>
            <p className="text-garage-text-muted mb-6">
              {t('dashboard.getStarted')}
            </p>
            <button
              onClick={() => setShowWizard(true)}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg"
            >
              <Plus className="w-5 h-5" />
              <span>{t('dashboard.addFirstVehicle')}</span>
            </button>
          </div>
        )}
      </div>

      {/* Vehicle Wizard Modal */}
      {showWizard && (
        <VehicleWizard
          onClose={() => setShowWizard(false)}
          onSuccess={handleVehicleCreated}
        />
      )}
    </>
  )
}
