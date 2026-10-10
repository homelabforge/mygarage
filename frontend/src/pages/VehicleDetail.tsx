/**
 * Vehicle Detail Page - Tabbed interface for vehicle information
 * Tabs: Overview, Photos, Service, Fuel, Notes
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ArrowLeft,
  Image,
  Wrench,
  Fuel,
  Bell,
  FileText,
  DollarSign,
  Info,
  Gauge,
  BarChart3,
  Shield,
  AlertTriangle,
  CreditCard,
  Landmark,
  MapPin,
  Radio,
  Activity,
  Clock,
  Droplets,
  Package,
  CircleDot,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import vehicleService from '../services/vehicleService'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { withBase } from '../utils/basePath'
import type { Vehicle } from '../types/vehicle'
import type { LastLocation } from '../types/trips'
import ServiceTab from '../components/tabs/ServiceTab'
import FuelTab from '../components/tabs/FuelTab'
import OdometerTab from '../components/tabs/OdometerTab'
import HoursTab from '../components/tabs/HoursTab'
import PhotosTab from '../components/tabs/PhotosTab'
import DocumentsTab from '../components/tabs/DocumentsTab'
import NotesTab from '../components/tabs/NotesTab'
import WarrantiesTab from '../components/tabs/WarrantiesTab'
import InsuranceTab from '../components/tabs/InsuranceTab'
import ReportsTab from '../components/tabs/ReportsTab'
import TollsTab from '../components/tabs/TollsTab'
import SuppliesUsedTab from '../components/SuppliesUsedTab'
import SafetyTab from '../components/tabs/SafetyTab'
import TaxRecordList from '../components/TaxRecordList'
import FinancingRecordList from '../components/FinancingRecordList'
import TireList from '../components/TireList'
import SpotRentalsTab from '../components/tabs/SpotRentalsTab'
import PropaneTab from '../components/tabs/PropaneTab'
import DEFTab from '../components/tabs/DEFTab'
import LiveLinkLiveTab from '../components/tabs/LiveLinkLiveTab'
import LiveLinkDTCsTab from '../components/tabs/LiveLinkDTCsTab'
import LiveLinkSessionsTab from '../components/tabs/LiveLinkSessionsTab'
import LiveLinkChartsTab from '../components/tabs/LiveLinkChartsTab'
import LiveLinkTripsTab from '../components/tabs/LiveLinkTripsTab'
import ReminderList from '../components/ReminderList'
import SubTabNav from '../components/SubTabNav'
import VehicleHero from '../components/vehicle-detail/VehicleHero'
import VehicleActionsToolbar from '../components/vehicle-detail/VehicleActionsToolbar'
import VehiclePrimaryTabs from '../components/vehicle-detail/VehiclePrimaryTabs'
import VehicleOverviewTab from '../components/vehicle-detail/VehicleOverviewTab'
import VehicleMobileActionsSheet from '../components/vehicle-detail/VehicleMobileActionsSheet'
import VehicleKeyFacts from '../components/vehicle-detail/VehicleKeyFacts'
import { livelinkService } from '../services/livelinkService'
import WindowStickerUpload from '../components/WindowStickerUpload'
import VehicleRemoveModal from '../components/modals/VehicleRemoveModal'
import VehicleTransferWizard from '../components/modals/VehicleTransferWizard'
import VehicleSharingModal from '../components/modals/VehicleSharingModal'
import EquipmentDrawer from '../components/vehicle-detail/EquipmentDrawer'
import PricingDrawer from '../components/vehicle-detail/PricingDrawer'
import VehicleFieldsDrawer, { type VehicleCardKey } from '../components/vehicle-detail/VehicleFieldsDrawer'
import VehicleEditDrawer from '../components/vehicle-detail/VehicleEditDrawer'
import TorqueSourceModal from '../components/modals/TorqueSourceModal'
import { useOnlineStatus } from '../hooks/useOnlineStatus'
import { useAuth } from '../contexts/AuthContext'
import { fillUpKind, vehicleLogKinds } from '../utils/vehicleLogKinds'
import { VehicleUnitScope } from '../contexts/VehicleUnitScope'
import { forgetCachedVehicle, readCachedVehicle, rememberVehicle } from '../utils/vehicleCache'
import { useSyncQuickEntryVehicle } from '../hooks/queries/useQuickEntryVehicles'
import { useVehicleDetailStats } from '../hooks/queries/useVehicleDetailStats'
import { buildImportSummary } from '../utils/importSummary'

export type ModalType = 'remove' | 'transfer' | 'sharing' | 'windowSticker' | 'torqueSource' | null
export type PrimaryTabType = 'overview' | 'media' | 'maintenance' | 'fuel' | 'tracking' | 'financial' | 'livelink'
export type SubTabType = 'photos' | 'documents' | 'service' | 'fuel' | 'def' | 'propane' | 'odometer' | 'hours' | 'notes' | 'warranties' | 'insurance' | 'tax' | 'tolls' | 'financing' | 'spotrentals' | 'suppliesused' | 'recalls' | 'reports' | 'reminders' | 'live' | 'dtcs' | 'sessions' | 'charts' | 'trips' | 'tires'

export default function VehicleDetail() {
  const { t } = useTranslation('vehicles')
  const { vin } = useParams<{ vin: string }>()
  const navigate = useNavigate()
  const { isAdmin } = useAuth()
  const [searchParams] = useSearchParams()
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activePrimaryTab, setActivePrimaryTab] = useState<PrimaryTabType>('overview')
  const [activeSubTab, setActiveSubTab] = useState<SubTabType | null>(null)
  const [openModal, setOpenModal] = useState<ModalType>(null)
  const [exporting, setExporting] = useState(false)
  const [importing, setImporting] = useState(false)
  const [fromCache, setFromCache] = useState(false)
  const [showMobileMenu, setShowMobileMenu] = useState(false)
  // Capabilities of every LiveLink device linked to this vehicle, unioned by
  // the backend. `null` means no linked device at all, which is what hides the
  // LiveLink primary tab; an empty array would mean a device whose kind
  // declares nothing, which is a different (and loggable) condition.
  const [liveLinkCaps, setLiveLinkCaps] = useState<string[] | null>(null)
  const [lastLocation, setLastLocation] = useState<LastLocation | null>(null)
  const [equipmentDrawer, setEquipmentDrawer] = useState<'standard' | 'optional' | null>(null)
  const [pricingDrawerOpen, setPricingDrawerOpen] = useState(false)
  const [editDrawerOpen, setEditDrawerOpen] = useState(false)
  // Which info card's editor sidecar is open. `fieldsCard` is kept set during
  // the close animation (only `fieldsOpen` flips), so the drawer's content
  // doesn't blank mid-exit.
  const [fieldsCard, setFieldsCard] = useState<VehicleCardKey | null>(null)
  const [fieldsOpen, setFieldsOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const isOnline = useOnlineStatus()

  // Kept out of loadVehicle's dependency array on purpose: the ref always
  // reads the latest translator without destabilizing the callback,
  // matching the established pattern in Dashboard.tsx.
  const tRef = useRef(t)
  useEffect(() => {
    tRef.current = t
  }, [t])

  const loadVehicle = useCallback(async () => {
    if (!vin) return
    setLoading(true)
    setError(null)
    setFromCache(false)

    try {
      const data = await vehicleService.get(vin)
      setVehicle(data)
      rememberVehicle(vin, data)
    } catch (error) {
      if (!navigator.onLine) {
        const cached = readCachedVehicle(vin)
        if (cached) {
          setVehicle(cached)
          setFromCache(true)
          return
        }
        // Absent or unreadable: an unreadable copy would fail the same way
        // next time, so it goes.
        forgetCachedVehicle(vin)
      }
      setError(getActionErrorMessage(error, tRef.current('detail.misc.loadAction')))
    } finally {
      setLoading(false)
    }
    // `t` intentionally excluded: react-i18next's mock (and some real setups)
    // hand back a fresh function identity per render. Depending on it here
    // re-fires this effect — and therefore refetches + remounts the whole
    // page — on every unrelated state update (e.g. a tab click), which is
    // both wasteful and, under jsdom, indistinguishable from a real remount
    // for any test asserting exact side-effect call counts (P5 Task 4).
  }, [vin])

  useEffect(() => {
    loadVehicle()
  }, [loadVehicle])

  const syncQuickEntryVehicle = useSyncQuickEntryVehicle()
  /**
   * Every sidecar save lands here, not in `setVehicle` (#172). Each one gets
   * the server's fresh row, which can carry an odometer unit changed on
   * another device, so the offline copy and the Quick Entry list follow it.
   */
  const handleVehicleUpdated = useCallback(
    (updated: Vehicle) => {
      setVehicle(updated)
      if (vin) rememberVehicle(vin, updated)
      syncQuickEntryVehicle(updated)
    },
    [vin, syncQuickEntryVehicle]
  )

  // What this vehicle's LiveLink sources can actually do. Gates both the
  // primary tab and its sub-tabs: a propane gateway declares telemetry alone,
  // and offering it DTCs, drive sessions or trips shows an OBD2 dashboard for
  // a sensor that will never fill one in.
  useEffect(() => {
    const loadLiveLinkCapabilities = async () => {
      if (!vin) return
      try {
        const status = await livelinkService.getVehicleStatus(vin)
        setLiveLinkCaps(status.device_id ? (status.capabilities ?? []) : null)
      } catch {
        // Silently fail - LiveLink tab just won't show
        setLiveLinkCaps(null)
      }
    }
    void loadLiveLinkCapabilities()
  }, [vin])

  // Values are `Capability` enum values from the backend registry
  // (`app/services/livelink_sources/base.py`), not free-form strings.
  const canLiveLink = useCallback(
    (capability: string): boolean => liveLinkCaps?.includes(capability) ?? false,
    [liveLinkCaps],
  )

  // Fetch the vehicle's most-recent GPS location for the Overview "Last seen
  // here" card (Task 16). Independent of hasLiveLinkDevice: Torque Pro
  // sources can post location data before any LiveLink device exists, and
  // the Overview tab (unlike the LiveLink primary tab) is always present.
  useEffect(() => {
    const fetchLastLocation = async () => {
      if (!vin) return
      try {
        const location = await livelinkService.getLastLocation(vin)
        setLastLocation(location)
      } catch {
        // Silently fail - card just won't show
        setLastLocation(null)
      }
    }
    fetchLastLocation()
  }, [vin])

  // The hero/key-facts read-aggregation (overdue/upcoming/reading/last-service/
  // last-fill-up/spent-YTD). Independent secondary fetch: the page never blocks
  // on it (the hero renders without the reading/badge, and the key-facts strip
  // is omitted until it resolves; no layout is reserved).
  //
  // On the query cache, keyed by vin, so any write refreshes it by key (#192):
  // the reminder, service-visit and tire invalidation helpers and every reading
  // write. The cache also covers the races the old generation counter did: a
  // late A response lands in A's entry and never shows on B (B3); a refresh
  // cancels the one in flight, so an older response can't overwrite a newer
  // one (codex R1-M2); and a write for A that finishes after navigating to B
  // only marks A stale, since A has no observer left to refetch for (codex
  // R2-M1). A failed refresh keeps the last good stats.
  const queryClient = useQueryClient()
  const { data: detailStats = null } = useVehicleDetailStats(vin ?? '')

  // Handle URL tab parameter from calendar navigation
  useEffect(() => {
    const tabParam = searchParams.get('tab')
    if (!tabParam) return

    // Map calendar tab parameter to primary + sub tab
    const tabMapping: Record<string, { primary: PrimaryTabType; sub: SubTabType }> = {
      'insurance': { primary: 'financial', sub: 'insurance' },
      'propane': { primary: 'fuel', sub: 'propane' },
      'def': { primary: 'fuel', sub: 'def' },
      'warranties': { primary: 'financial', sub: 'warranties' },
      'service': { primary: 'maintenance', sub: 'service' },
      'notes': { primary: 'tracking', sub: 'notes' },
      'fuel': { primary: 'fuel', sub: 'fuel' },
      'odometer': { primary: 'maintenance', sub: 'odometer' },
      'photos': { primary: 'media', sub: 'photos' },
      'documents': { primary: 'media', sub: 'documents' },
      'tax': { primary: 'financial', sub: 'tax' },
      'tolls': { primary: 'financial', sub: 'tolls' },
      'financing': { primary: 'financial', sub: 'financing' },
      'spotrentals': { primary: 'financial', sub: 'spotrentals' },
      'recalls': { primary: 'maintenance', sub: 'recalls' },
      'tires': { primary: 'maintenance', sub: 'tires' },
      'reports': { primary: 'tracking', sub: 'reports' },
      'reminders': { primary: 'tracking', sub: 'reminders' },
      'live': { primary: 'livelink', sub: 'live' },
      'dtcs': { primary: 'livelink', sub: 'dtcs' },
      'sessions': { primary: 'livelink', sub: 'sessions' },
      'charts': { primary: 'livelink', sub: 'charts' },
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
      toast.error(t('detail.connectToExport'))
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
      toast.success(t('detail.exportSuccess'))
    } catch (err) {
      toast.error(t('detail.exportError'), {
        description: getActionErrorMessage(err, t('detail.exportAction'))
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
      toast.error(t('detail.connectToImport'))
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
      toast.success(t('detail.importSuccess'), {
        description: buildImportSummary(response.data, t)
      })

      // Reload the vehicle data
      await loadVehicle()
      // An import can write every record type, reminders and readings
      // included, and vehicle-scoped query keys don't share one shape (the
      // insurance key puts the VIN third), so mark everything stale. Only
      // what's on screen refetches (#192).
      void queryClient.invalidateQueries()
    } catch (err) {
      toast.error(t('detail.importError'), {
        description: getActionErrorMessage(err, t('detail.importAction'))
      })
    } finally {
      setImporting(false)
      // Reset file input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    }
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
      case 'fuel':
        // Fuel group is fuel/def/propane; pick the first sub-tab visible for this
        // vehicle (propane-only trailers aren't motorized, so 'fuel' would be hidden).
        // Order matches the Add Fuel hero button (config order Fuel -> DEF -> Propane).
        setActiveSubTab(fillUpKind({ ...logKinds, def: logKinds.defHistory }) ?? 'fuel')
        break
      case 'tracking':
        setActiveSubTab('notes')
        break
      case 'financial':
        setActiveSubTab('warranties')
        break
      case 'overview':
        setActiveSubTab(null)
        break
      case 'livelink':
        setActiveSubTab('live')
        break
    }
  }

  // Handle sub-tab click
  const handleSubTabClick = (subTabId: string) => {
    setActiveSubTab(subTabId as SubTabType)
  }

  // Hero action buttons switch to the relevant tab + sub-tab (SDQ-1) — pure
  // navigation, no P6-owned drawer state lifted into P5.
  const goToSection = (primary: PrimaryTabType, sub: SubTabType) => {
    setActivePrimaryTab(primary)
    setActiveSubTab(sub)
  }

  // Equipment pill (SDQ-2): open the equipment editor sidecar for the requested
  // list. The drawer is portalled, so it works from any tab — no tab switch.
  const handleEquipmentClick = (which: 'standard' | 'optional') => {
    setEquipmentDrawer(which)
  }

  // Overview info-card click (Basic Information / Vehicle Details / Powertrain /
  // Warranty): open the shared field editor sidecar for that card.
  const openFieldsCard = (card: VehicleCardKey) => {
    setFieldsCard(card)
    setFieldsOpen(true)
  }

  // Download window sticker with authentication
  const handleDownloadWindowSticker = async () => {
    if (!vin) return
    try {
      const response = await api.get(`/vehicles/${vin}/window-sticker/file`, {
        responseType: 'blob',
      })
      const contentTypeHeader = response.headers['content-type']
      const contentType = typeof contentTypeHeader === 'string' ? contentTypeHeader : undefined
      const blob = new Blob([response.data], { type: contentType })
      const url = window.URL.createObjectURL(blob)
      window.open(url, '_blank')
      // Clean up after a delay
      setTimeout(() => window.URL.revokeObjectURL(url), 10000)
    } catch {
      toast.error(t('detail.windowStickerDownloadError'))
    }
  }

  // Which records this vehicle logs: the fuel group's sub-tabs, Odometer vs.
  // Hours, tires. Quick Entry reads the same rule, so the two cannot drift.
  // RVs ARE motorized and keep fuel/odometer tabs; trailers are not.
  const logKinds = vehicleLogKinds(vehicle)
  const isMotorized = logKinds.motorized
  const showFuelLog = logKinds.fuel

  // Equipment-presence flags (B7) — the actions toolbar hides an Equipment
  // button when its <details> target (below, in VehicleOverviewTab) is absent.
  // Optional-chained into a local so no `vehicle.standard_equipment` non-null
  // deref is written (B5 — strict-clean); `vehicle` is still `Vehicle | null`
  // here, before the `!vehicle` early return.
  const standardEquipment = vehicle?.standard_equipment
  const hasStandardEquipment = Boolean(
    standardEquipment &&
    typeof standardEquipment === 'object' &&
    Object.keys(standardEquipment).length > 0,
  )
  const optionalEquipment = vehicle?.optional_equipment
  const hasOptionalEquipment = Boolean(
    optionalEquipment &&
    typeof optionalEquipment === 'object' &&
    Object.keys(optionalEquipment).length > 0,
  )

  const hasPropane = logKinds.propane
  // Either fuel slot, as the API gates DEF writes; the DEF tab renders
  // read-only otherwise.
  const isDiesel = logKinds.def
  // Diesel, or a DEF tank set: legacy non-diesel DEF history stays visible.
  const hasDEF = logKinds.defHistory

  // Check if vehicle is RV, Fifth Wheel, or Travel Trailer (for spot rentals)
  const isRVOrFifthWheel = vehicle?.vehicle_type != null &&
    ['RV', 'FifthWheel', 'TravelTrailer'].includes(vehicle.vehicle_type)

  // Primary tabs configuration
  const primaryTabs = [
    {
      id: 'overview' as const,
      label: t('detail.tabs.overview'),
      icon: Info,
      hasSubTabs: false
    },
    {
      id: 'media' as const,
      label: t('detail.tabs.media'),
      icon: Image,
      hasSubTabs: true
    },
    {
      id: 'maintenance' as const,
      label: t('detail.tabs.maintenance'),
      icon: Wrench,
      hasSubTabs: true
    },
    // Fuel tab — groups fuel/DEF/propane fill-ups; shown when any is relevant
    ...((showFuelLog || hasDEF || hasPropane) ? [{
      id: 'fuel' as const,
      label: t('detail.tabs.fuel'),
      icon: Fuel,
      hasSubTabs: true
    }] : []),
    {
      id: 'tracking' as const,
      label: t('detail.tabs.tracking'),
      icon: Bell,
      hasSubTabs: true
    },
    {
      id: 'financial' as const,
      label: t('detail.tabs.financial'),
      icon: DollarSign,
      hasSubTabs: true
    },
    // LiveLink tab - only visible when vehicle has linked device
    ...(liveLinkCaps !== null ? [{
      id: 'livelink' as const,
      label: 'LiveLink',
      icon: Radio,
      hasSubTabs: true
    }] : []),
  ]

  // Sub-tabs for each primary tab
  const subTabsConfig: Record<string, Array<{ id: SubTabType; label: string; icon: LucideIcon; visible?: boolean }>> = {
    media: [
      { id: 'photos' as const, label: t('detail.misc.photos'), icon: Image },
      { id: 'documents' as const, label: t('documentList.title'), icon: FileText },
    ],
    maintenance: [
      { id: 'service' as const, label: t('vehicleStats.service'), icon: Wrench },
      { id: 'odometer' as const, label: t('detail.misc.odometer'), icon: Gauge, visible: logKinds.odometer },
      { id: 'hours' as const, label: t('common:engineHours'), icon: Clock, visible: logKinds.hours },
      { id: 'tires' as const, label: t('detail.misc.tires'), icon: CircleDot, visible: isMotorized },
      { id: 'recalls' as const, label: t('detail.misc.recalls'), icon: AlertTriangle },
    ],
    fuel: [
      { id: 'fuel' as const, label: t('detail.tabs.fuel'), icon: Fuel, visible: showFuelLog },
      // i18n-exempt — DEF is an untranslated acronym (Diesel Exhaust Fluid)
      { id: 'def' as const, label: 'DEF', icon: Droplets, visible: hasDEF },
      { id: 'propane' as const, label: t('detail.misc.propane'), icon: Fuel, visible: hasPropane },
    ],
    tracking: [
      { id: 'notes' as const, label: t('noteList.title'), icon: FileText },
      { id: 'reminders' as const, label: t('reminderList.title'), icon: Bell },
      { id: 'reports' as const, label: t('detail.misc.reports'), icon: BarChart3 },
    ],
    financial: [
      { id: 'warranties' as const, label: t('warrantyList.title'), icon: Shield },
      { id: 'insurance' as const, label: t('detail.misc.insurance'), icon: Shield },
      { id: 'tax' as const, label: t('detail.misc.taxRegistration'), icon: DollarSign },
      { id: 'tolls' as const, label: t('detail.misc.tolls'), icon: CreditCard },
      { id: 'financing' as const, label: t('financingList.title'), icon: Landmark },
      { id: 'spotrentals' as const, label: t('spotRentalList.title'), icon: MapPin, visible: isRVOrFifthWheel },
      { id: 'suppliesused' as const, label: t('detail.misc.supplies'), icon: Package },
    ],
    // Each sub-tab is gated on the Capability that fills it. Live and Charts
    // need only TELEMETRY, which every source declares, so they are ungated.
    livelink: [
      { id: 'live' as const, label: t('detail.misc.live'), icon: Activity },
      // i18n-exempt — DTCs is an untranslated acronym (Diagnostic Trouble Codes)
      { id: 'dtcs' as const, label: 'DTCs', icon: AlertTriangle, visible: canLiveLink('dtc') },
      { id: 'sessions' as const, label: t('detail.misc.sessions'), icon: Clock, visible: canLiveLink('drive_session') },
      { id: 'charts' as const, label: t('detail.misc.charts'), icon: BarChart3 },
      { id: 'trips' as const, label: t('detail.misc.trips'), icon: MapPin, visible: canLiveLink('location') },
    ],
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen" role="status" aria-label={t('detail.loading')}>
        <div className="h-12 w-12 rounded-full border-4 border-[color:var(--accent-solid)] border-t-transparent animate-spin" />
        <span className="sr-only">{t('detail.loading')}</span>
      </div>
    )
  }

  if (error || !vehicle) {
    return (
      <div className="mx-auto max-w-[1120px] px-[clamp(16px,3vw,30px)] py-8">
        <div className="rounded-panel border border-danger bg-danger/10 p-6 text-center">
          <p className="mb-4 text-danger">{error || t('detail.vehicleNotFound')}</p>
          <Link
            to="/"
            className="inline-flex items-center gap-2 rounded-control border border-border bg-surface px-4 py-2 hover:bg-surface-2 transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            <span>{t('detail.backToDashboard')}</span>
          </Link>
        </div>
      </div>
    )
  }

  const photoUrl = vehicle.main_photo
    ? withBase(`/api/vehicles/${vehicle.vin}/photos/${vehicle.main_photo.split('/').pop()}`)
    : null

  const page = (
    <div className="min-h-screen bg-bg pb-8">
      <div className="mx-auto max-w-[1120px] px-[clamp(16px,3vw,30px)] pt-6">
        {/* Back link (prototype dc.html:243) */}
        <Link
          to="/"
          className="mb-4 inline-flex items-center gap-1.5 text-sm text-text-mute hover:text-text transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>{t('detail.backToGarage')}</span>
        </Link>

        {/* Hero */}
        <VehicleHero vehicle={vehicle} photoUrl={photoUrl} fromCache={fromCache} detailStats={detailStats} />

        {/* Hidden file input for import */}
        <input ref={fileInputRef} type="file" accept=".json" onChange={handleImportJSON} className="hidden" />

        {/* Actions row + secondary toolbar (Task 4 restyle) */}
        <VehicleActionsToolbar
          isAdmin={isAdmin}
          importing={importing}
          exporting={exporting}
          isOnline={isOnline}
          showFuelAction={Boolean(showFuelLog || hasDEF || hasPropane)}
          hasStandardEquipment={hasStandardEquipment}
          hasOptionalEquipment={hasOptionalEquipment}
          onLogService={() => goToSection('maintenance', 'service')}
          onAddFuel={() => goToSection('fuel', fillUpKind({ ...logKinds, def: logKinds.defHistory }) ?? 'fuel')}
          onReminder={() => goToSection('tracking', 'reminders')}
          onEditEquipment={handleEquipmentClick}
          onEdit={() => setEditDrawerOpen(true)}
          onAnalytics={() => navigate(`/vehicles/${vin}/analytics`)}
          onImport={handleImportClick}
          onExport={handleExportJSON}
          onOpenModal={setOpenModal}
          onOpenMobileMenu={() => setShowMobileMenu(true)}
        />

        {/* Key-facts strip (P5 Task 5) */}
        {detailStats && <VehicleKeyFacts stats={detailStats} />}

        {/* Primary tabs */}
        <VehiclePrimaryTabs tabs={primaryTabs} activeTab={activePrimaryTab} onTabClick={handlePrimaryTabClick} />
      </div>

      {/* Sub-tabs (if applicable) — hidden when only one sub-tab is visible, so
          a lone entry (e.g. a gasoline vehicle's Fuel group) doesn't render a
          strip that just duplicates its parent tab. */}
      {activePrimaryTab !== 'overview' && subTabsConfig[activePrimaryTab] &&
        subTabsConfig[activePrimaryTab].filter((sub) => sub.visible !== false).length > 1 && (
        <SubTabNav
          tabs={subTabsConfig[activePrimaryTab]}
          activeTab={activeSubTab || ''}
          onTabChange={handleSubTabClick}
          label={t('detail.misc.subSections')}
        />
      )}

      {/* Tab Content */}
      <div
        role="tabpanel"
        id={`panel-${activePrimaryTab}`}
        aria-labelledby={`tab-mobile-${activePrimaryTab} tab-desktop-${activePrimaryTab}`}
        className="container mx-auto px-4 py-8"
      >
        {activePrimaryTab === 'overview' && (
          <VehicleOverviewTab
            vin={vin!}
            vehicle={vehicle}
            lastLocation={lastLocation}
            onEditPricing={() => setPricingDrawerOpen(true)}
            onEditCard={openFieldsCard}
            onVehicleUpdated={handleVehicleUpdated}
          />
        )}

        {/* Media Sub-tabs */}
        {activePrimaryTab === 'media' && activeSubTab === 'photos' && vin && <PhotosTab vin={vin} />}
        {activePrimaryTab === 'media' && activeSubTab === 'documents' && vin && <DocumentsTab vin={vin} />}

        {/* Maintenance & Fuel Sub-tabs */}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'service' && vin && <ServiceTab vin={vin} />}
        {activePrimaryTab === 'fuel' && activeSubTab === 'fuel' && vin && <FuelTab vin={vin} />}
        {activePrimaryTab === 'fuel' && activeSubTab === 'def' && vin && <DEFTab vin={vin} isDiesel={isDiesel} />}
        {activePrimaryTab === 'fuel' && activeSubTab === 'propane' && vin && <PropaneTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'odometer' && vin && <OdometerTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'hours' && vin && <HoursTab vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'tires' && vin && <TireList vin={vin} />}
        {activePrimaryTab === 'maintenance' && activeSubTab === 'recalls' && vin && <SafetyTab vin={vin} />}

        {/* Tracking Sub-tabs */}
        {activePrimaryTab === 'tracking' && activeSubTab === 'notes' && vin && <NotesTab vin={vin} />}
        {activePrimaryTab === 'tracking' && activeSubTab === 'reminders' && vin && <ReminderList vin={vin} />}
        {activePrimaryTab === 'tracking' && activeSubTab === 'reports' && vin && <ReportsTab vin={vin} />}

        {/* Financial Sub-tabs */}
        {activePrimaryTab === 'financial' && activeSubTab === 'warranties' && vin && <WarrantiesTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'insurance' && vin && <InsuranceTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'tax' && vin && <TaxRecordList vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'tolls' && vin && <TollsTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'financing' && vin && <FinancingRecordList vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'spotrentals' && vin && <SpotRentalsTab vin={vin} />}
        {activePrimaryTab === 'financial' && activeSubTab === 'suppliesused' && vin && <SuppliesUsedTab vin={vin} />}

        {/* LiveLink Sub-tabs */}
        {activePrimaryTab === 'livelink' && activeSubTab === 'live' && vin && <LiveLinkLiveTab vin={vin} />}
        {/* Capability is re-checked here, not just on the tab strip: these
            sub-tabs are deep-linkable by query string (`?tab=dtcs`), which
            reaches the content without ever passing a hidden button. */}
        {activePrimaryTab === 'livelink' && activeSubTab === 'dtcs' && canLiveLink('dtc') && vin && <LiveLinkDTCsTab vin={vin} />}
        {activePrimaryTab === 'livelink' && activeSubTab === 'sessions' && canLiveLink('drive_session') && vin && <LiveLinkSessionsTab vin={vin} />}
        {activePrimaryTab === 'livelink' && activeSubTab === 'charts' && vin && <LiveLinkChartsTab vin={vin} />}
        {activePrimaryTab === 'livelink' && activeSubTab === 'trips' && canLiveLink('location') && vin && <LiveLinkTripsTab vin={vin} />}
      </div>

      {/* Vehicle Remove Modal */}
      <VehicleRemoveModal
        isOpen={openModal === 'remove'}
        onClose={() => setOpenModal(null)}
        vehicle={vehicle}
        onConfirm={handleVehicleRemoved}
      />

      {/* Vehicle Transfer Wizard */}
      {vin && vehicle && (
        <VehicleTransferWizard
          isOpen={openModal === 'transfer'}
          onClose={() => setOpenModal(null)}
          vin={vin}
          vehicleNickname={vehicle.nickname}
          onTransferComplete={() => {
            // Reload vehicle to get updated owner
            loadVehicle()
          }}
        />
      )}

      {/* Vehicle Sharing Modal */}
      {vin && vehicle && (
        <VehicleSharingModal
          isOpen={openModal === 'sharing'}
          onClose={() => setOpenModal(null)}
          vin={vin}
          vehicleNickname={vehicle.nickname}
        />
      )}

      {/* Equipment editor sidecar (opened from the Equipment pills) */}
      {vin && vehicle && (
        <EquipmentDrawer
          open={equipmentDrawer !== null}
          which={equipmentDrawer ?? 'standard'}
          vehicle={vehicle}
          vin={vin}
          onClose={() => setEquipmentDrawer(null)}
          onUpdated={handleVehicleUpdated}
        />
      )}

      {/* Pricing editor sidecar (opened from the Pricing card) */}
      {vin && vehicle && (
        <PricingDrawer
          open={pricingDrawerOpen}
          vehicle={vehicle}
          vin={vin}
          onClose={() => setPricingDrawerOpen(false)}
          onUpdated={handleVehicleUpdated}
        />
      )}

      {/* Shared info-card editor sidecar (Basic Info / Details / Powertrain /
          Warranty), opened by clicking the corresponding Overview card. */}
      {vin && vehicle && (
        <VehicleFieldsDrawer
          open={fieldsOpen}
          card={fieldsCard}
          isMotorized={Boolean(isMotorized)}
          vehicle={vehicle}
          vin={vin}
          onClose={() => setFieldsOpen(false)}
          onUpdated={handleVehicleUpdated}
        />
      )}

      {/* Vehicle edit sidecar (opened from the toolbar Edit button and the
          mobile actions sheet — formerly the /vehicles/:vin/edit page) */}
      {vin && vehicle && (
        <VehicleEditDrawer
          open={editDrawerOpen}
          vin={vin}
          vehicle={vehicle}
          onClose={() => setEditDrawerOpen(false)}
          onUpdated={handleVehicleUpdated}
          onDownloadWindowSticker={handleDownloadWindowSticker}
          onUploadWindowSticker={() => setOpenModal('windowSticker')}
          onManageTorqueSources={() => setOpenModal('torqueSource')}
        />
      )}

      {/* Torque Source Modal (Task 13, owner-reachable) */}
      {vin && (
        <TorqueSourceModal
          isOpen={openModal === 'torqueSource'}
          onClose={() => setOpenModal(null)}
          vin={vin}
        />
      )}

      {/* Mobile Actions Menu */}
      {showMobileMenu && (
        <VehicleMobileActionsSheet
          vin={vin!}
          isAdmin={isAdmin}
          importing={importing}
          exporting={exporting}
          isOnline={isOnline}
          onImportClick={handleImportClick}
          onExport={handleExportJSON}
          onOpenModal={setOpenModal}
          onClose={() => setShowMobileMenu(false)}
          onEdit={() => setEditDrawerOpen(true)}
        />
      )}

      {/* Window Sticker Upload Modal */}
      {openModal === 'windowSticker' && vin && (
        <WindowStickerUpload
          vin={vin}
          hasExistingSticker={!!vehicle?.window_sticker_file_path}
          onSuccess={() => {
            setOpenModal(null)
            loadVehicle()
            toast.success(t('detail.windowStickerUploaded'))
          }}
          onClose={() => setOpenModal(null)}
        />
      )}
    </div>
  )

  // Every tab, drawer and record form reads the vehicle's odometer unit
  // through this scope (#172). Keyed on the unit: a sidecar save can land
  // AFTER its drawer was dismissed (the drawers do not block closing
  // mid-save), and if it changes the unit while a record form is open, that
  // form would read typed miles as kilometres. A unit change remounts
  // everything below instead, closing any open form: a lost draft in a rare
  // race, never a silently wrong reading. A save that keeps the unit remounts
  // nothing.
  return (
    <VehicleUnitScope key={vehicle.distance_unit ?? 'account'} distanceUnit={vehicle.distance_unit}>
      {page}
    </VehicleUnitScope>
  )
}
