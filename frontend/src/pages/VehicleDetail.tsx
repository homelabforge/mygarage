/**
 * Vehicle Detail Page - Tabbed interface for vehicle information
 * Tabs: Overview, Photos, Service, Fuel, Reminders, Notes
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom'
import { toast } from 'sonner'
import {
  ArrowLeft,
  Edit,
  Trash2,
  Car,
  Image,
  Wrench,
  Fuel,
  Bell,
  FileText,
  Calendar,
  DollarSign,
  Info,
  Gauge,
  Download,
  Upload,
  BarChart3,
  Shield,
  AlertTriangle,
  CreditCard,
  MapPin,
  MoreVertical,
  X,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import vehicleService from '../services/vehicleService'
import api from '../services/api'
import type { Vehicle } from '../types/vehicle'
import ServiceTab from '../components/tabs/ServiceTab'
import FuelTab from '../components/tabs/FuelTab'
import OdometerTab from '../components/tabs/OdometerTab'
import PhotosTab from '../components/tabs/PhotosTab'
import DocumentsTab from '../components/tabs/DocumentsTab'
import RemindersTab from '../components/tabs/RemindersTab'
import NotesTab from '../components/tabs/NotesTab'
import WarrantiesTab from '../components/tabs/WarrantiesTab'
import InsuranceTab from '../components/tabs/InsuranceTab'
import ReportsTab from '../components/tabs/ReportsTab'
import TollsTab from '../components/tabs/TollsTab'
import SafetyTab from '../components/tabs/SafetyTab'
import TaxRecordList from '../components/TaxRecordList'
import SpotRentalsTab from '../components/tabs/SpotRentalsTab'
import PropaneTab from '../components/tabs/PropaneTab'
import SubTabNav from '../components/SubTabNav'
import WindowStickerUpload from '../components/WindowStickerUpload'
import VehicleRemoveModal from '../components/modals/VehicleRemoveModal'
import { useOnlineStatus } from '../hooks/useOnlineStatus'

type ApiError = {
  response?: {
    data?: {
      detail?: string
    }
  }
  message?: string
}

const getApiErrorMessage = (error: unknown, fallback: string) => {
  if (error && typeof error === 'object') {
    const apiError = error as ApiError
    if (apiError.response?.data?.detail) {
      return apiError.response.data.detail
    }
    if (apiError.message) {
      return apiError.message
    }
  }

  if (error instanceof Error) {
    return error.message
  }

  return fallback
}

type PrimaryTabType = 'overview' | 'media' | 'maintenance' | 'tracking' | 'financial'
type SubTabType = 'photos' | 'documents' | 'service' | 'fuel' | 'propane' | 'odometer' | 'reminders' | 'notes' | 'warranties' | 'insurance' | 'tax' | 'tolls' | 'spotrentals' | 'recalls' | 'reports'

export default function VehicleDetail() {
  const { vin } = useParams<{ vin: string }>()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activePrimaryTab, setActivePrimaryTab] = useState<PrimaryTabType>('overview')
  const [activeSubTab, setActiveSubTab] = useState<SubTabType | null>(null)
  const [showRemoveModal, setShowRemoveModal] = useState(false)
  const [showWindowStickerUpload, setShowWindowStickerUpload] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [fromCache, setFromCache] = useState(false)
  const [showMobileMenu, setShowMobileMenu] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isOnline = useOnlineStatus()
  const loadVehicle = useCallback(async () => {
    if (!vin) return
    const cacheKey = `vehicle-cache-${vin}`
    setLoading(true)
    setError(null)
    setFromCache(false)

    try {
      const data = await vehicleService.get(vin)
      setVehicle(data)
      localStorage.setItem(cacheKey, JSON.stringify({ timestamp: Date.now(), data }))
    } catch (error) {
      if (!navigator.onLine) {
        const cached = localStorage.getItem(cacheKey)
        if (cached) {
          const parsed = JSON.parse(cached)
          setVehicle(parsed.data)
          setFromCache(true)
          setError('Offline: showing cached vehicle data.')
          return
        }
      }
      setError(getApiErrorMessage(error, 'Failed to load vehicle'))
    } finally {
      setLoading(false)
    }
  }, [vin])

  useEffect(() => {
    loadVehicle()
  }, [loadVehicle])

  // Handle URL tab parameter from calendar navigation
  useEffect(() => {
    const tabParam = searchParams.get('tab')
    if (!tabParam) return

    // Map calendar tab parameter to primary + sub tab
    const tabMapping: Record<string, { primary: PrimaryTabType; sub: SubTabType }> = {
      'reminders': { primary: 'tracking', sub: 'reminders' },
      'insurance': { primary: 'financial', sub: 'insurance' },
      'propane': { primary: 'maintenance', sub: 'propane' },
      'warranties': { primary: 'financial', sub: 'warranties' },
      'service': { primary: 'maintenance', sub: 'service' },
      'notes': { primary: 'tracking', sub: 'notes' },
      'fuel': { primary: 'maintenance', sub: 'fuel' },
      'odometer': { primary: 'maintenance', sub: 'odometer' },
      'photos': { primary: 'media', sub: 'photos' },
      'documents': { primary: 'media', sub: 'documents' },
      'tax': { primary: 'financial', sub: 'tax' },
      'tolls': { primary: 'financial', sub: 'tolls' },
      'spotrentals': { primary: 'financial', sub: 'spotrentals' },
      'recalls': { primary: 'maintenance', sub: 'recalls' },
      'reports': { primary: 'tracking', sub: 'reports' },
    }

    const mapping = tabMapping[tabParam]
    if (mapping) {
      setActivePrimaryTab(mapping.primary)
      setActiveSubTab(mapping.sub)
    }
  }, [searchParams])

  const handleVehicleRemoved = () => {
    // Navigate home after vehicle is removed (archived or deleted)
    navigate('/')
  }

  const handleExportJSON = async () => {
    if (!vin) return
    if (!isOnline) {
      toast.error('Connect to the internet to export data.')
      return
    }

    setExporting(true)
    try {
      const response = await api.get(`/export/vehicles/${vin}/json`, {
        responseType: 'blob'
      })

      // Get the filename from Content-Disposition header
      const contentDisposition = response.headers['content-disposition']
      const filenameMatch = contentDisposition?.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : 'vehicle_data.json'

      // Download the file
      const blob = response.data
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
      toast.success('Vehicle data exported successfully')
    } catch (err) {
      toast.error('Failed to export data', {
        description: err instanceof Error ? err.message : undefined
      })
    } finally {
      setExporting(false)
    }
  }

  const handleImportClick = () => {
    fileInputRef.current?.click()
  }

  const handleImportJSON = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file || !vin) return
    if (!isOnline) {
      toast.error('Connect to the internet to import data.')
      return
    }

    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await api.post(`/import/vehicles/${vin}/json`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })
      const result = response.data

      // Show results
      let message = 'Import completed:\n'
      if (result.service_records) {
        message += `\nService Records: ✓ ${result.service_records.success_count} imported`
        if (result.service_records.skipped_count > 0) {
          message += `, ○ ${result.service_records.skipped_count} skipped`
        }
        if (result.service_records.error_count > 0) {
          message += `, ✗ ${result.service_records.error_count} errors`
        }
      }
      if (result.fuel_records) {
        message += `\nFuel Records: ✓ ${result.fuel_records.success_count} imported`
        if (result.fuel_records.skipped_count > 0) {
          message += `, ○ ${result.fuel_records.skipped_count} skipped`
        }
        if (result.fuel_records.error_count > 0) {
          message += `, ✗ ${result.fuel_records.error_count} errors`
        }
      }
      if (result.odometer_records) {
        message += `\nOdometer Records: ✓ ${result.odometer_records.success_count} imported`
        if (result.odometer_records.skipped_count > 0) {
          message += `, ○ ${result.odometer_records.skipped_count} skipped`
        }
        if (result.odometer_records.error_count > 0) {
          message += `, ✗ ${result.odometer_records.error_count} errors`
        }
      }
      if (result.reminders) {
        message += `\nReminders: ✓ ${result.reminders.success_count} imported`
        if (result.reminders.skipped_count > 0) {
          message += `, ○ ${result.reminders.skipped_count} skipped`
        }
        if (result.reminders.error_count > 0) {
          message += `, ✗ ${result.reminders.error_count} errors`
        }
      }
      if (result.notes) {
        message += `\nNotes: ✓ ${result.notes.success_count} imported`
        if (result.notes.skipped_count > 0) {
          message += `, ○ ${result.notes.skipped_count} skipped`
        }
        if (result.notes.error_count > 0) {
          message += `, ✗ ${result.notes.error_count} errors`
        }
      }

      toast.success('Import completed successfully', {
        description: message
      })

      // Reload the vehicle data
      await loadVehicle()
    } catch (err) {
      toast.error('Failed to import data', {
        description: err instanceof Error ? err.message : undefined
      })
    } finally {
      setImporting(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
  }

  const formatDate = (dateString?: string) => {
    if (!dateString) return 'Not specified'
    const date = new Date(dateString)
    return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
  }

  const formatPrice = (price?: number) => {
    if (!price) return 'Not specified'
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
    }).format(price)
  }

  // Handle primary tab click
  const handlePrimaryTabClick = (tabId: PrimaryTabType) => {
    setActivePrimaryTab(tabId)

    // Set default sub-tab when switching primary tabs
    switch (tabId) {
      case 'media':
        setActiveSubTab('photos')
        break
      case 'maintenance':
        setActiveSubTab('service')
        break
      case 'tracking':
        setActiveSubTab('reminders')
        break
      case 'financial':
        setActiveSubTab('warranties')
        break
      case 'overview':
        setActiveSubTab(null)
        break
    }
  }

  // Handle sub-tab click
  const handleSubTabClick = (subTabId: string) => {
    setActiveSubTab(subTabId as SubTabType)
  }

  // Download window sticker with authentication
  const handleDownloadWindowSticker = async () => {
    if (!vin) return
    try {
      const response = await api.get(`/vehicles/${vin}/window-sticker/file`, {
        responseType: 'blob',
      })
      const blob = new Blob([response.data], { type: response.headers['content-type'] })
      const url = window.URL.createObjectURL(blob)
      window.open(url, '_blank')
      // Clean up after a delay
      setTimeout(() => window.URL.revokeObjectURL(url), 10000)
    } catch {
      toast.error('Failed to download window sticker')
    }
  }

  // Check if vehicle is motorized (excludes non-motorized trailers, fifth wheels, and travel trailers)
  // RVs ARE motorized and keep fuel/odometer tabs
  const isMotorized = vehicle?.vehicle_type &&
    !['Trailer', 'FifthWheel', 'TravelTrailer'].includes(vehicle.vehicle_type)

  // Check if vehicle is a fifth wheel, travel trailer, or RV (for propane tracking)
  const hasPropane = vehicle?.vehicle_type &&
    ['RV', 'FifthWheel', 'TravelTrailer'].includes(vehicle.vehicle_type)

  // Check if vehicle is RV, Fifth Wheel, or Travel Trailer (for spot rentals)
  const isRVOrFifthWheel = vehicle?.vehicle_type &&
    ['RV', 'FifthWheel', 'TravelTrailer'].includes(vehicle.vehicle_type)

  // Primary tabs configuration
  const primaryTabs = [
    {
      id: 'overview' as const,
      label: 'Overview',
      icon: Info,
      hasSubTabs: false
    },
    {
      id: 'media' as const,
      label: 'Media',
      icon: Image,
      hasSubTabs: true
    },
    {
      id: 'maintenance' as const,
      label: 'Maintenance',
      icon: Wrench,
      hasSubTabs: true
    },
    {
      id: 'tracking' as const,
      label: 'Tracking',
      icon: Bell,
      hasSubTabs: true
    },
    {
      id: 'financial' as const,
      label: 'Financial',
      icon: DollarSign,
      hasSubTabs: true
    },
  ]

  // Sub-tabs for each primary tab
  const subTabsConfig: Record<string, Array<{ id: SubTabType; label: string; icon: LucideIcon; visible?: boolean }>> = {
    media: [
      { id: 'photos' as const, label: 'Photos', icon: Image },
      { id: 'documents' as const, label: 'Documents', icon: FileText },
    ],
    maintenance: [
      { id: 'service' as const, label: 'Service', icon: Wrench },
      { id: 'fuel' as const, label: 'Fuel', icon: Fuel, visible: isMotorized },
      { id: 'propane' as const, label: 'Propane', icon: Fuel, visible: hasPropane },
      { id: 'odometer' as const, label: 'Odometer', icon: Gauge, visible: isMotorized },
      { id: 'recalls' as const, label: 'Recalls', icon: AlertTriangle },
    ],
    tracking: [
      { id: 'reminders' as const, label: 'Reminders', icon: Bell },
      { id: 'notes' as const, label: 'Notes', icon: FileText },
      { id: 'reports' as const, label: 'Reports', icon: BarChart3 },
    ],
    financial: [
      { id: 'warranties' as const, label: 'Warranties', icon: Shield },
      { id: 'insurance' as const, label: 'Insurance', icon: Shield },
      { id: 'tax' as const, label: 'Tax & Registration', icon: DollarSign },
      { id: 'tolls' as const, label: 'Tolls', icon: CreditCard },
      { id: 'spotrentals' as const, label: 'Spot Rentals', icon: MapPin, visible: isRVOrFifthWheel },
    ],
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="w-12 h-12 border-4 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error || !vehicle) {
    return (
      <div className="container mx-auto px-4 py-8">
        <div className="bg-danger/10 border border-danger rounded-lg p-6 text-center">
          <p className="text-danger mb-4">{error || 'Vehicle not found'}</p>
          <Link
            to="/"
            className="inline-flex items-center space-x-2 px-4 py-2 bg-garage-surface border border-garage-border rounded-lg hover:bg-garage-bg transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Dashboard</span>
          </Link>
        </div>
      </div>
    )
  }

  const photoUrl = vehicle.main_photo
    ? `/api/vehicles/${vehicle.vin}/photos/${vehicle.main_photo.split('/').pop()}`
    : null

  return (
    <div className="min-h-screen bg-garage-bg pb-8">
      {/* Header */}
      <div className="bg-garage-surface border-b border-garage-border">
        <div className="container mx-auto px-4 py-6">
          <div className="flex items-start justify-between">
            <div className="flex items-start space-x-4">
              {/* Vehicle Photo */}
              <div className="w-24 h-24 bg-garage-bg rounded-lg overflow-hidden flex-shrink-0">
                {photoUrl ? (
                  <img
                    src={photoUrl}
                    alt={vehicle.nickname}
                    className="w-full h-full object-cover"
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <Car className="w-12 h-12 text-garage-text-muted opacity-20" />
                  </div>
                )}
              </div>

              {/* Vehicle Info */}
              <div>
                <Link
                  to="/"
                  className="inline-flex items-center space-x-1 text-sm text-garage-text-muted hover:text-garage-text transition-colors mb-2"
                >
                  <ArrowLeft className="w-3 h-3" />
                  <span>Back to Garage</span>
                </Link>
                <h1 className="text-3xl font-bold text-garage-text mb-1">{vehicle.nickname}</h1>
                <p className="text-garage-text-muted mb-2">
                  {[vehicle.year, vehicle.make, vehicle.model].filter(Boolean).join(' ')}
                </p>
                <div className="flex items-center space-x-4 text-sm">
                  <span className="text-garage-text-muted font-mono">{vehicle.vin}</span>
                  <span className="px-2 py-1 bg-garage-bg text-garage-text text-xs font-medium rounded">
                    {vehicle.vehicle_type}
                  </span>
                  {vehicle.sold_date && (
                    <span className="px-2 py-1 bg-warning/10 text-warning text-xs font-medium rounded">
                      Sold
                    </span>
                  )}
                </div>
                {fromCache && (
                  <div className="mt-2 flex items-center gap-2 text-xs text-amber-500">
                    <AlertTriangle className="w-4 h-4" />
                    <span>Offline: showing cached data</span>
                  </div>
                )}
              </div>
            </div>

            {/* Actions - Desktop: horizontal buttons, Mobile: overflow menu */}
            <div className="flex items-center space-x-2">
              {/* Hidden file input for import */}
              <input
                ref={fileInputRef}
                type="file"
                accept=".json"
                onChange={handleImportJSON}
                className="hidden"
              />

              {/* Desktop buttons - hidden on mobile */}
              <div className="hidden md:flex items-center space-x-2">
                <button
                  onClick={handleImportClick}
                  disabled={importing || !isOnline}
                  className="flex items-center space-x-2 px-5 py-3 btn btn-primary rounded-lg disabled:opacity-50"
                  title="Import vehicle data from JSON"
                >
                  <Upload className="w-4 h-4" />
                  <span>{importing ? 'Importing...' : 'Import'}</span>
                </button>
                <button
                  onClick={handleExportJSON}
                  disabled={exporting || !isOnline}
                  className="flex items-center space-x-2 px-5 py-3 btn btn-primary rounded-lg disabled:opacity-50"
                  title="Export complete vehicle data as JSON"
                >
                  <Download className="w-4 h-4" />
                  <span>{exporting ? 'Exporting...' : 'Export'}</span>
                </button>
                <button
                  onClick={() => navigate(`/vehicles/${vin}/analytics`)}
                  className="flex items-center space-x-2 px-5 py-3 btn btn-primary rounded-lg"
                  title="View analytics and reports"
                >
                  <BarChart3 className="w-4 h-4" />
                  <span>Analytics</span>
                </button>
                <button
                  onClick={() => navigate(`/vehicles/${vin}/edit`)}
                  className="flex items-center space-x-2 px-5 py-3 btn btn-primary rounded-lg"
                >
                  <Edit className="w-4 h-4" />
                  <span>Edit</span>
                </button>
                <button
                  onClick={() => setShowRemoveModal(true)}
                  className="flex items-center space-x-2 px-5 py-3 bg-red-900/30 border border-red-700 text-red-400 rounded-lg hover:bg-red-800/50 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                  <span>Remove</span>
                </button>
              </div>

              {/* Mobile overflow menu button */}
              <button
                onClick={() => setShowMobileMenu(true)}
                className="md:hidden flex items-center justify-center p-3 btn-primary"
                title="More actions"
              >
                <MoreVertical className="w-5 h-5" />
              </button>
            </div>
          </div>

          {/* Primary Tabs */}
          <div className="flex items-center space-x-1 mt-6 border-b border-garage-border -mb-px overflow-x-auto scrollbar-hide">
            {primaryTabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activePrimaryTab === tab.id

              return (
                <button
                  key={tab.id}
                  onClick={() => handlePrimaryTabClick(tab.id)}
                  className={`flex items-center space-x-2 px-4 py-3 border-b-2 transition-colors whitespace-nowrap ${
                    isActive
                      ? 'border-primary text-primary'
                      : 'border-transparent text-garage-text-muted hover:text-garage-text hover:border-garage-border'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  <span>{tab.label}</span>
                </button>
              )
            })}
          </div>
        </div>
      </div>

      {/* Sub-tabs (if applicable) */}
      {activePrimaryTab !== 'overview' && subTabsConfig[activePrimaryTab] && (
        <SubTabNav
          tabs={subTabsConfig[activePrimaryTab]}
          activeTab={activeSubTab || ''}
          onTabChange={handleSubTabClick}
        />
      )}

      {/* Tab Content */}
      <div className="container mx-auto px-4 py-8">
        {activePrimaryTab === 'overview' && (
          <div className="columns-1 lg:columns-2 gap-6 space-y-6">
            {/* Basic Information */}
            <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
              <h2 className="text-xl font-semibold text-garage-text mb-4">Basic Information</h2>
              <div className="space-y-3">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-garage-text-muted">Year</p>
                    <p className="text-garage-text font-medium">{vehicle.year || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Make</p>
                    <p className="text-garage-text font-medium">{vehicle.make || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Model</p>
                    <p className="text-garage-text font-medium">{vehicle.model || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">Exterior Color</p>
                    <p className="text-garage-text font-medium">{vehicle.exterior_color || vehicle.color || 'Not specified'}</p>
                  </div>
                  {vehicle.interior_color && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Interior Color</p>
                      <p className="text-garage-text font-medium">{vehicle.interior_color}</p>
                    </div>
                  )}
                  <div>
                    <p className="text-sm text-garage-text-muted">License Plate</p>
                    <p className="text-garage-text font-medium">{vehicle.license_plate || 'Not specified'}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted">VIN</p>
                    <p className="text-garage-text font-mono text-sm">{vehicle.vin}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Purchase Information */}
            <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
              <h2 className="text-xl font-semibold text-garage-text mb-4">Purchase Information</h2>
              <div className="space-y-3">
                <div>
                  <p className="text-sm text-garage-text-muted flex items-center space-x-2">
                    <Calendar className="w-4 h-4" />
                    <span>Purchase Date</span>
                  </p>
                  <p className="text-garage-text font-medium mt-1">{formatDate(vehicle.purchase_date)}</p>
                </div>
                <div>
                  <p className="text-sm text-garage-text-muted flex items-center space-x-2">
                    <DollarSign className="w-4 h-4" />
                    <span>Purchase Price</span>
                  </p>
                  <p className="text-garage-text font-medium mt-1">{formatPrice(vehicle.purchase_price)}</p>
                </div>
              </div>
            </div>

            {/* Sale Information (if sold) */}
            {vehicle.sold_date && (
              <div className="bg-garage-surface rounded-lg border border-warning p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Sale Information</h2>
                <div className="space-y-3">
                  <div>
                    <p className="text-sm text-garage-text-muted flex items-center space-x-2">
                      <Calendar className="w-4 h-4" />
                      <span>Sale Date</span>
                    </p>
                    <p className="text-garage-text font-medium mt-1">{formatDate(vehicle.sold_date)}</p>
                  </div>
                  <div>
                    <p className="text-sm text-garage-text-muted flex items-center space-x-2">
                      <DollarSign className="w-4 h-4" />
                      <span>Sale Price</span>
                    </p>
                    <p className="text-garage-text font-medium mt-1">{formatPrice(vehicle.sold_price)}</p>
                  </div>
                </div>
              </div>
            )}

            {/* VIN Decoded Information */}
            {(vehicle.trim || vehicle.body_class || vehicle.drive_type || vehicle.doors || vehicle.gvwr_class || vehicle.wheel_specs || vehicle.tire_specs || (!isMotorized && vehicle.fuel_type)) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Vehicle Details</h2>
                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {vehicle.trim && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Trim</p>
                        <p className="text-garage-text font-medium">{vehicle.trim}</p>
                      </div>
                    )}
                    {vehicle.body_class && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Body Class</p>
                        <p className="text-garage-text font-medium">{vehicle.body_class}</p>
                      </div>
                    )}
                    {vehicle.drive_type && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Drive Type</p>
                        <p className="text-garage-text font-medium">{vehicle.drive_type}</p>
                      </div>
                    )}
                    {vehicle.doors && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Doors</p>
                        <p className="text-garage-text font-medium">{vehicle.doors}</p>
                      </div>
                    )}
                    {vehicle.gvwr_class && (
                      <div>
                        <p className="text-sm text-garage-text-muted">GVWR Class</p>
                        <p className="text-garage-text font-medium">{vehicle.gvwr_class}</p>
                      </div>
                    )}
                    {vehicle.wheel_specs && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Wheels</p>
                        <p className="text-garage-text font-medium">{vehicle.wheel_specs}</p>
                      </div>
                    )}
                    {vehicle.tire_specs && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Tires</p>
                        <p className="text-garage-text font-medium">{vehicle.tire_specs}</p>
                      </div>
                    )}
                    {/* Show fuel type in Vehicle Details for non-motorized vehicles (e.g., propane for fifth wheels) */}
                    {!isMotorized && vehicle.fuel_type && (
                      <div>
                        <p className="text-sm text-garage-text-muted">Fuel Type</p>
                        <p className="text-garage-text font-medium">{vehicle.fuel_type}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Powertrain (Engine & Transmission) - Only show for motorized vehicles */}
            {isMotorized && (vehicle.displacement_l || vehicle.cylinders || vehicle.fuel_type || vehicle.sticker_engine_description || vehicle.transmission_type || vehicle.transmission_speeds || vehicle.sticker_transmission_description || vehicle.sticker_drivetrain) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Powertrain</h2>
                <div className="space-y-3">
                  {/* Engine Section */}
                  {(vehicle.displacement_l || vehicle.cylinders || vehicle.fuel_type || vehicle.sticker_engine_description) && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      {vehicle.sticker_engine_description && (
                        <div className="md:col-span-2">
                          <p className="text-sm text-garage-text-muted">Engine</p>
                          <p className="text-garage-text font-medium">{vehicle.sticker_engine_description}</p>
                        </div>
                      )}
                      {vehicle.displacement_l && (
                        <div>
                          <p className="text-sm text-garage-text-muted">Displacement</p>
                          <p className="text-garage-text font-medium">{vehicle.displacement_l} L</p>
                        </div>
                      )}
                      {vehicle.cylinders && (
                        <div>
                          <p className="text-sm text-garage-text-muted">Cylinders</p>
                          <p className="text-garage-text font-medium">{vehicle.cylinders}</p>
                        </div>
                      )}
                      {vehicle.fuel_type && (
                        <div>
                          <p className="text-sm text-garage-text-muted">Fuel Type</p>
                          <p className="text-garage-text font-medium">{vehicle.fuel_type}</p>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Transmission Section */}
                  {(vehicle.transmission_type || vehicle.transmission_speeds || vehicle.sticker_transmission_description) && (
                    <div className={(vehicle.displacement_l || vehicle.cylinders || vehicle.fuel_type || vehicle.sticker_engine_description) ? 'pt-3 border-t border-garage-border' : ''}>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {vehicle.sticker_transmission_description && (
                          <div className="md:col-span-2">
                            <p className="text-sm text-garage-text-muted">Transmission</p>
                            <p className="text-garage-text font-medium">{vehicle.sticker_transmission_description}</p>
                          </div>
                        )}
                        {vehicle.transmission_type && (
                          <div>
                            <p className="text-sm text-garage-text-muted">Type</p>
                            <p className="text-garage-text font-medium">{vehicle.transmission_type}</p>
                          </div>
                        )}
                        {vehicle.transmission_speeds && (
                          <div>
                            <p className="text-sm text-garage-text-muted">Speeds</p>
                            <p className="text-garage-text font-medium">{vehicle.transmission_speeds}</p>
                          </div>
                        )}
                        {vehicle.sticker_drivetrain && (
                          <div>
                            <p className="text-sm text-garage-text-muted">Drivetrain</p>
                            <p className="text-garage-text font-medium">{vehicle.sticker_drivetrain}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* MSRP & Pricing */}
            {(vehicle.msrp_base || vehicle.msrp_options || vehicle.msrp_total || vehicle.destination_charge) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">MSRP Pricing</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {vehicle.msrp_base && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Base Price</p>
                      <p className="text-garage-text font-medium">${vehicle.msrp_base.toLocaleString()}</p>
                    </div>
                  )}
                  {vehicle.msrp_options && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Options</p>
                      <p className="text-garage-text font-medium">${vehicle.msrp_options.toLocaleString()}</p>
                    </div>
                  )}
                  {vehicle.destination_charge && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Destination</p>
                      <p className="text-garage-text font-medium">${vehicle.destination_charge.toLocaleString()}</p>
                    </div>
                  )}
                  {vehicle.msrp_total && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Total MSRP</p>
                      <p className="text-garage-text font-medium text-lg">${vehicle.msrp_total.toLocaleString()}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Fuel Economy */}
            {(vehicle.fuel_economy_city || vehicle.fuel_economy_highway || vehicle.fuel_economy_combined) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Fuel Economy</h2>
                <div className="grid grid-cols-3 gap-4">
                  {vehicle.fuel_economy_city && (
                    <div>
                      <p className="text-sm text-garage-text-muted">City</p>
                      <p className="text-garage-text font-medium">{vehicle.fuel_economy_city} MPG</p>
                    </div>
                  )}
                  {vehicle.fuel_economy_highway && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Highway</p>
                      <p className="text-garage-text font-medium">{vehicle.fuel_economy_highway} MPG</p>
                    </div>
                  )}
                  {vehicle.fuel_economy_combined && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Combined</p>
                      <p className="text-garage-text font-medium">{vehicle.fuel_economy_combined} MPG</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Warranty */}
            {(vehicle.warranty_powertrain || vehicle.warranty_basic) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Warranty</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {vehicle.warranty_basic && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Basic</p>
                      <p className="text-garage-text font-medium">{vehicle.warranty_basic}</p>
                    </div>
                  )}
                  {vehicle.warranty_powertrain && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Powertrain</p>
                      <p className="text-garage-text font-medium">{vehicle.warranty_powertrain}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Environmental Ratings */}
            {(vehicle.environmental_rating_ghg || vehicle.environmental_rating_smog) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Environmental Ratings</h2>
                <div className="grid grid-cols-2 gap-4">
                  {vehicle.environmental_rating_ghg && (
                    <div>
                      <p className="text-sm text-garage-text-muted">GHG Rating</p>
                      <p className="text-garage-text font-medium">{vehicle.environmental_rating_ghg}</p>
                    </div>
                  )}
                  {vehicle.environmental_rating_smog && (
                    <div>
                      <p className="text-sm text-garage-text-muted">Smog Rating</p>
                      <p className="text-garage-text font-medium">{vehicle.environmental_rating_smog}</p>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Assembly Location */}
            {vehicle.assembly_location && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Manufacturing</h2>
                <div>
                  <p className="text-sm text-garage-text-muted">Assembly Location</p>
                  <p className="text-garage-text font-medium">{vehicle.assembly_location}</p>
                </div>
              </div>
            )}

            {/* Standard Equipment - Collapsible */}
            {vehicle.standard_equipment && typeof vehicle.standard_equipment === 'object' && Object.keys(vehicle.standard_equipment).length > 0 && (
              <details className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid group">
                <summary className="text-xl font-semibold text-garage-text cursor-pointer list-none flex items-center justify-between">
                  <span>Standard Equipment</span>
                  <span className="text-sm font-normal text-garage-text-muted group-open:rotate-180 transition-transform">▼</span>
                </summary>
                <div className="space-y-3 mt-4">
                  {Object.entries(vehicle.standard_equipment).map(([category, items]) => (
                    <div key={category}>
                      {/* Hide "items" category header - it's just a container */}
                      {category !== 'items' && (
                        <p className="text-sm font-medium text-primary mb-2">{category}</p>
                      )}
                      {Array.isArray(items) ? (
                        <ul className="list-disc list-inside space-y-1">
                          {items.map((item, idx) => (
                            <li key={idx} className="text-sm text-garage-text">{item}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="text-sm text-garage-text">{String(items)}</p>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Optional Equipment with Pricing - Collapsible */}
            {vehicle.optional_equipment && typeof vehicle.optional_equipment === 'object' && Object.keys(vehicle.optional_equipment).length > 0 && (
              <details className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid group">
                <summary className="text-xl font-semibold text-garage-text cursor-pointer list-none flex items-center justify-between">
                  <span>Optional Equipment</span>
                  <span className="text-sm font-normal text-garage-text-muted group-open:rotate-180 transition-transform">▼</span>
                </summary>
                <div className="space-y-2 mt-4">
                  {Object.entries(vehicle.optional_equipment).map(([category, items]) => (
                    <div key={category}>
                      {/* Hide "items" category header - it's just a container */}
                      {category !== 'items' && (
                        <p className="text-sm font-medium text-primary mb-2">{category}</p>
                      )}
                      {Array.isArray(items) ? (
                        <ul className="space-y-1">
                          {items.map((item, idx) => {
                            const price = vehicle.window_sticker_options_detail?.[item as string]
                            return (
                              <li key={idx} className="text-sm text-garage-text flex justify-between">
                                <span>{item}</span>
                                {price && <span className="text-garage-text-muted">${price}</span>}
                              </li>
                            )
                          })}
                        </ul>
                      ) : (
                        <p className="text-sm text-garage-text">{String(items)}</p>
                      )}
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Packages */}
            {vehicle.window_sticker_packages && typeof vehicle.window_sticker_packages === 'object' && Object.keys(vehicle.window_sticker_packages).length > 0 && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <h2 className="text-xl font-semibold text-garage-text mb-4">Packages</h2>
                <div className="space-y-2">
                  {Object.entries(vehicle.window_sticker_packages).map(([packageName, price]) => (
                    <div key={packageName} className="flex justify-between items-center">
                      <span className="text-sm text-garage-text">{packageName}</span>
                      {price && <span className="text-sm text-garage-text-muted">${price}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Window Sticker - Only show for cars/trucks */}
            {vehicle.vehicle_type && ['Car', 'Truck', 'SUV'].includes(vehicle.vehicle_type) && (
              <div className="bg-garage-surface rounded-lg border border-garage-border p-6 break-inside-avoid">
                <div className="flex items-center justify-between mb-4">
                  <h2 className="text-xl font-semibold text-garage-text">Window Sticker</h2>
                  <Link
                    to={`/vehicles/${vin}/window-sticker-test`}
                    className="text-xs px-2 py-1 bg-garage-bg rounded text-garage-text-muted hover:text-primary transition-colors"
                  >
                    Test OCR
                  </Link>
                </div>
                {vehicle.window_sticker_file_path ? (
                  <div className="space-y-3">
                    <button
                      onClick={handleDownloadWindowSticker}
                      className="w-full group cursor-pointer"
                    >
                      <div className="h-20 bg-garage-bg rounded-lg border border-garage-border overflow-hidden flex items-center justify-center gap-3 hover:bg-garage-border/30 transition-colors">
                        <FileText className="w-8 h-8 text-primary" />
                        <div className="text-left">
                          <p className="text-sm font-medium text-garage-text">View Window Sticker</p>
                          <p className="text-xs text-garage-text-muted">Click to open PDF</p>
                        </div>
                      </div>
                    </button>
                    {/* OCR Metadata */}
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-garage-text-muted">
                      {vehicle.window_sticker_parser_used && (
                        <span>Parser: {vehicle.window_sticker_parser_used}</span>
                      )}
                      {vehicle.window_sticker_confidence_score && (
                        <span>Confidence: {Number(vehicle.window_sticker_confidence_score).toFixed(0)}%</span>
                      )}
                      {vehicle.window_sticker_extracted_vin && (
                        <span className={vehicle.window_sticker_extracted_vin === vehicle.vin ? 'text-success' : 'text-warning'}>
                          VIN: {vehicle.window_sticker_extracted_vin === vehicle.vin ? '✓ Verified' : '⚠ Mismatch'}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => setShowWindowStickerUpload(true)}
                      className="text-sm text-garage-text-muted hover:text-garage-text transition-colors"
                    >
                      Replace sticker...
                    </button>
                  </div>
                ) : (
                  <div className="text-center py-4">
                    <FileText className="w-10 h-10 text-garage-text-muted mx-auto mb-2 opacity-50" />
                    <p className="text-sm text-garage-text-muted mb-3">No window sticker uploaded</p>
                    <button
                      onClick={() => setShowWindowStickerUpload(true)}
                      className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm"
                    >
                      Upload Window Sticker
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Media Sub-tabs */}
        {activePrimaryTab === 'media' && activeSubTab === 'photos' && vin && <PhotosTab vin={vin} />}
        {activePrimaryTab === 'media' && activeSubTab === 'documents' && vin && <DocumentsTab vin={vin} />}

        {/* Maintenance Sub-tabs */}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'service' && vin && <ServiceTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'fuel' && vin && <FuelTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'propane' && vin && <PropaneTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'odometer' && vin && <OdometerTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'recalls' && vin && <SafetyTab vin={vin} />}

        {/* Tracking Sub-tabs */}
        {activePrimaryTab === 'tracking' && activeSubTab === 'reminders' && vin && <RemindersTab vin={vin} />}
        {activePrimaryTab === 'tracking' && activeSubTab === 'notes' && vin && <NotesTab vin={vin} />}
        {activePrimaryTab === 'tracking' && activeSubTab === 'reports' && vin && <ReportsTab vin={vin} />}

        {/* Financial Sub-tabs */}
        {activePrimaryTab === 'financial' && activeSubTab === 'warranties' && vin && <WarrantiesTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'insurance' && vin && <InsuranceTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'tax' && vin && <TaxRecordList vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'tolls' && vin && <TollsTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'spotrentals' && vin && <SpotRentalsTab vin={vin} />}
      </div>

      {/* Vehicle Remove Modal */}
      <VehicleRemoveModal
        isOpen={showRemoveModal}
        onClose={() => setShowRemoveModal(false)}
        vehicle={vehicle}
        onConfirm={handleVehicleRemoved}
      />

      {/* Mobile Actions Menu */}
      {showMobileMenu && (
        <div className="fixed inset-0 bg-black/50 flex items-end justify-center z-50 md:hidden" onClick={() => setShowMobileMenu(false)}>
          <div className="bg-garage-surface rounded-t-2xl w-full max-w-lg pb-safe" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-garage-border">
              <h3 className="text-lg font-semibold text-garage-text">Actions</h3>
              <button
                onClick={() => setShowMobileMenu(false)}
                className="p-2 text-garage-text-muted hover:text-garage-text rounded-lg transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-2">
              <button
                onClick={() => {
                  handleImportClick()
                  setShowMobileMenu(false)
                }}
                disabled={importing || !isOnline}
                className="w-full flex items-center space-x-3 px-4 py-3 text-left text-garage-text hover:bg-garage-bg rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Upload className="w-5 h-5" />
                <span>{importing ? 'Importing...' : 'Import Data'}</span>
              </button>
              <button
                onClick={() => {
                  handleExportJSON()
                  setShowMobileMenu(false)
                }}
                disabled={exporting || !isOnline}
                className="w-full flex items-center space-x-3 px-4 py-3 text-left text-garage-text hover:bg-garage-bg rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Download className="w-5 h-5" />
                <span>{exporting ? 'Exporting...' : 'Export Data'}</span>
              </button>
              <button
                onClick={() => {
                  navigate(`/vehicles/${vin}/analytics`)
                  setShowMobileMenu(false)
                }}
                className="w-full flex items-center space-x-3 px-4 py-3 text-left text-garage-text hover:bg-garage-bg rounded-lg transition-colors"
              >
                <BarChart3 className="w-5 h-5" />
                <span>View Analytics</span>
              </button>
              <button
                onClick={() => {
                  navigate(`/vehicles/${vin}/edit`)
                  setShowMobileMenu(false)
                }}
                className="w-full flex items-center space-x-3 px-4 py-3 text-left text-garage-text hover:bg-garage-bg rounded-lg transition-colors"
              >
                <Edit className="w-5 h-5" />
                <span>Edit Vehicle</span>
              </button>
              <button
                onClick={() => {
                  setShowMobileMenu(false)
                  setShowRemoveModal(true)
                }}
                className="w-full flex items-center space-x-3 px-4 py-3 text-left text-red-400 hover:bg-red-900/20 rounded-lg transition-colors"
              >
                <Trash2 className="w-5 h-5" />
                <span>Remove Vehicle</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Window Sticker Upload Modal */}
      {showWindowStickerUpload && vin && (
        <WindowStickerUpload
          vin={vin}
          onSuccess={() => {
            setShowWindowStickerUpload(false)
            loadVehicle()
            toast.success('Window sticker uploaded successfully!')
          }}
          onClose={() => setShowWindowStickerUpload(false)}
        />
      )}
    </div>
  )
}
