import { useState, useEffect, useMemo } from 'react'
import { useLocation } from 'react-router-dom'
import { Plus, Car as CarIcon, SlidersHorizontal, Filter } from 'lucide-react'
import VehicleStatisticsCard from '../components/VehicleStatisticsCard'
import VehicleWizard from '../components/VehicleWizard'
import type { DashboardResponse } from '../types/dashboard'
import api from '../services/api'

type SortOption = 'name' | 'year-new' | 'year-old' | 'reminders'
type FilterOption = 'all' | 'owned' | 'shared'

export default function Dashboard() {
  const location = useLocation()
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [showWizard, setShowWizard] = useState(false)
  const [sortBy, setSortBy] = useState<SortOption>('name')
  const [filterBy, setFilterBy] = useState<FilterOption>('all')

  useEffect(() => {
    // Load dashboard data when component mounts or navigation occurs
    loadDashboard()
  }, [location.key])

  const loadDashboard = async () => {
    try {
      const response = await api.get('/dashboard')
      setDashboard(response.data)
    } catch {
      // Silent fail - dashboard will show loading state
    } finally {
      setLoading(false)
    }
  }

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
          return b.year - a.year
        case 'year-old':
          return a.year - b.year
        case 'reminders':
          // Sort by overdue count (desc), then upcoming count (desc)
          if (b.overdue_reminders_count !== a.overdue_reminders_count) {
            return b.overdue_reminders_count - a.overdue_reminders_count
          }
          return b.upcoming_reminders_count - a.upcoming_reminders_count
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
            <h1 className="text-3xl font-bold mb-2 text-garage-text">My Garage</h1>
            <p className="text-garage-text-muted">
              {vehicleCount > 0
                ? `Managing ${vehicleCount} vehicle${vehicleCount !== 1 ? 's' : ''}`
                : 'Manage your vehicles and track maintenance'}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Filter - only show if there are shared vehicles */}
            {vehicleCount > 0 && hasSharedVehicles && (
              <div className="relative">
                <select
                  value={filterBy}
                  onChange={(e) => setFilterBy(e.target.value as FilterOption)}
                  className="pl-3 pr-10 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text appearance-none cursor-pointer"
                >
                  <option value="all" className="bg-garage-bg text-garage-text">
                    All Vehicles
                  </option>
                  <option value="owned" className="bg-garage-bg text-garage-text">
                    My Vehicles
                  </option>
                  <option value="shared" className="bg-garage-bg text-garage-text">
                    Shared With Me
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
                  className="pl-3 pr-10 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text appearance-none cursor-pointer"
                >
                  <option value="name" className="bg-garage-bg text-garage-text">
                    Sort by Name
                  </option>
                  <option value="year-new" className="bg-garage-bg text-garage-text">
                    Newest First
                  </option>
                  <option value="year-old" className="bg-garage-bg text-garage-text">
                    Oldest First
                  </option>
                  <option value="reminders" className="bg-garage-bg text-garage-text">
                    By Reminders
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
              <span>Add Vehicle</span>
            </button>
          </div>
        </div>

        {/* Vehicles Grid */}
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
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
            <h3 className="text-xl font-semibold mb-2 text-garage-text">No Vehicles Yet</h3>
            <p className="text-garage-text-muted mb-6">
              Get started by adding your first vehicle
            </p>
            <button
              onClick={() => setShowWizard(true)}
              className="inline-flex items-center gap-2 btn btn-primary rounded-lg"
            >
              <Plus className="w-5 h-5" />
              <span>Add Your First Vehicle</span>
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
