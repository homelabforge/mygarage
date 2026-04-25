import { useState, useEffect, useCallback, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Calendar as CalendarIcon, Filter, AlertCircle, CheckCircle, RotateCw, Clock, Wrench, Search, Download, Gauge, X, CheckSquare, Square, MessageCircle } from 'lucide-react'
import { useCalendarApp, ScheduleXCalendar } from '@schedule-x/react'
import { createViewDay, createViewWeek, createViewMonthGrid } from '@schedule-x/calendar'
import { createEventsServicePlugin } from '@schedule-x/events-service'
import { createCalendarControlsPlugin } from '@schedule-x/calendar-controls'
import 'temporal-polyfill/global'
import '@schedule-x/theme-default/dist/index.css'
import { format, startOfMonth, endOfMonth, subMonths, addMonths, startOfDay, endOfDay, addDays, differenceInDays, isBefore, isAfter } from 'date-fns'
import { toast } from 'sonner'
import { useNavigate } from 'react-router-dom'
import type { CalendarEvent, CalendarResponse } from '../types/calendar'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'
import { useUnitPreference } from '../hooks/useUnitPreference'
import { UnitFormatter, UnitConverter } from '../utils/units'

// Map event type -> Schedule-X calendarId for per-type coloring
const EVENT_CALENDARS = {
  maintenance: {
    colorName: 'maintenance',
    lightColors: { main: '#3b82f6', container: '#dbeafe', onContainer: '#1e3a5f' },
    darkColors: { main: '#60a5fa', onContainer: '#bfdbfe', container: '#1e3a8a' },
  },
  insurance: {
    colorName: 'insurance',
    lightColors: { main: '#ef4444', container: '#fee2e2', onContainer: '#7f1d1d' },
    darkColors: { main: '#f87171', onContainer: '#fecaca', container: '#991b1b' },
  },
  warranty: {
    colorName: 'warranty',
    lightColors: { main: '#f59e0b', container: '#fef3c7', onContainer: '#78350f' },
    darkColors: { main: '#fbbf24', onContainer: '#fde68a', container: '#92400e' },
  },
  service: {
    colorName: 'service',
    lightColors: { main: '#6b7280', container: '#f3f4f6', onContainer: '#374151' },
    darkColors: { main: '#9ca3af', onContainer: '#d1d5db', container: '#4b5563' },
  },
} as const

export default function CalendarPage() {
  const { t } = useTranslation('vehicles')
  const navigate = useNavigate()
  const { system } = useUnitPreference()
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [summary, setSummary] = useState({ total: 0, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 0 })
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedVehicles, setSelectedVehicles] = useState<string[]>([])
  const [selectedTypes, setSelectedTypes] = useState<string[]>(['maintenance', 'insurance', 'warranty'])
  const [showHistory, setShowHistory] = useState(false)
  const [date, setDate] = useState(new Date())

  // Schedule-X plugins (stable refs via useState initializer)
  const [eventsService] = useState(() => createEventsServicePlugin())
  const [calendarControls] = useState(() => createCalendarControlsPlugin())

  // Detect dark mode from <html> class
  const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark')

  const calendar = useCalendarApp({
    views: [createViewMonthGrid(), createViewWeek(), createViewDay()],
    defaultView: 'month-grid',
    selectedDate: Temporal.PlainDate.from(format(new Date(), 'yyyy-MM-dd')),
    isDark,
    calendars: EVENT_CALENDARS,
    callbacks: {
      onEventClick(calendarEvent) {
        // calendarEvent._customData holds the original CalendarEvent
        const original = calendarEvent._customData as CalendarEvent | undefined
        if (!original) return
        const [type] = original.id.split('-')
        switch (type) {
          case 'maintenance':
            navigate(`/vehicles/${original.vehicle_vin}?tab=maintenance`)
            break
          case 'insurance':
            navigate(`/vehicles/${original.vehicle_vin}?tab=insurance`)
            break
          case 'warranty':
            navigate(`/vehicles/${original.vehicle_vin}?tab=warranties`)
            break
          case 'service':
            navigate(`/vehicles/${original.vehicle_vin}?tab=service`)
            break
        }
      },
      onRangeUpdate(range) {
        // range.start may be a Temporal object or string like "2026-06-01 00:00"
        // Extract YYYY-MM-DD and use noon to avoid timezone edge cases
        const dateStr = String(range.start).slice(0, 10)
        const parsed = new Date(dateStr + 'T12:00:00')
        if (!isNaN(parsed.getTime())) {
          setDate(parsed)
        }
      },
    },
    plugins: [eventsService, calendarControls],
  })

  // Phase 3 state
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedEvents, setSelectedEvents] = useState<string[]>([])
  const [bulkMode, setBulkMode] = useState(false)
  const [bulkCompleting, setBulkCompleting] = useState(false)
  const [showNotesModal, setShowNotesModal] = useState(false)
  const [selectedEventForNotes, setSelectedEventForNotes] = useState<CalendarEvent | null>(null)

  // Cache state for smooth month navigation
  const [cachedStartDate, setCachedStartDate] = useState<string | null>(null)
  const [cachedEndDate, setCachedEndDate] = useState<string | null>(null)

  // Fetch vehicles
  const loadVehicles = useCallback(async () => {
    try {
      const response = await api.get('/vehicles')
      setVehicles(response.data.vehicles || [])
    } catch {
      toast.error(t('calendar.loadVehiclesError'))
    }
  }, [t])

  // Fetch calendar events
  const loadEvents = useCallback(async () => {
    try {
      // Calculate desired date range (6 months: 3 before, 3 after current month)
      const desiredStartDate = format(startOfMonth(subMonths(date, 3)), 'yyyy-MM-dd')
      const desiredEndDate = format(endOfMonth(addMonths(date, 3)), 'yyyy-MM-dd')

      // Check if we already have data for this range
      const needsRefetch = !cachedStartDate || !cachedEndDate ||
        isBefore(new Date(desiredStartDate), new Date(cachedStartDate)) ||
        isAfter(new Date(desiredEndDate), new Date(cachedEndDate))

      // If current data covers the range, skip the fetch (smooth navigation!)
      if (!needsRefetch) {
        // Data already cached - no need to show loading or refetch
        setLoading(false)
        return
      }

      setLoading(true)

      const params = new URLSearchParams({
        start_date: desiredStartDate,
        end_date: desiredEndDate,
      })

      if (selectedVehicles.length > 0) {
        params.append('vehicle_vins', selectedVehicles.join(','))
      }

      const types = [...selectedTypes]
      if (showHistory) types.push('service')

      if (types.length > 0 && types.length < 4) {
        params.append('event_types', types.join(','))
      }

      const response = await api.get(`/calendar?${params}`)
      const data: CalendarResponse = response.data
      setEvents(data.events || [])
      setSummary(data.summary)

      // Update cache range
      setCachedStartDate(desiredStartDate)
      setCachedEndDate(desiredEndDate)
    } catch {
      toast.error(t('calendar.loadEventsError'))
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, selectedVehicles, selectedTypes, showHistory, cachedStartDate, cachedEndDate])

  useEffect(() => {
    loadVehicles()
  }, [loadVehicles])

  // Invalidate cache when filters change (not date)
  useEffect(() => {
    setCachedStartDate(null)
    setCachedEndDate(null)
  }, [selectedVehicles, selectedTypes, showHistory])

  useEffect(() => {
    loadEvents()
  }, [loadEvents])

  // Phase 3: Filter events by search query
  const filteredEvents = useMemo(() => {
    if (!searchQuery.trim()) return events

    const query = searchQuery.toLowerCase()
    return events.filter(e =>
      e.title.toLowerCase().includes(query) ||
      e.description?.toLowerCase().includes(query) ||
      e.vehicle_nickname?.toLowerCase().includes(query) ||
      e.vehicle_vin.toLowerCase().includes(query)
    )
  }, [events, searchQuery])

  // Sync filtered events into Schedule-X events service
  useEffect(() => {
    const sxEvents = filteredEvents.map(event => {
      const dateStr = event.date.split('T')[0]
      const pd = Temporal.PlainDate.from(dateStr)
      return {
        id: event.id,
        title: event.title,
        start: pd,
        end: pd,
        calendarId: event.type as string,
        _customData: event,
      }
    })
    eventsService.set(sxEvents)
  }, [filteredEvents, eventsService])

  // Get upcoming events (next 30 days, not completed)
  const upcomingEvents = useMemo(() => {
    const today = startOfDay(new Date())
    const thirtyDaysLater = endOfDay(addDays(new Date(), 30))

    return filteredEvents
      .filter(e => !e.is_completed && e.urgency !== 'historical')
      .filter(e => {
        const eventDate = new Date(e.date)
        return !isBefore(eventDate, today) && !isAfter(eventDate, thirtyDaysLater)
      })
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime())
      .slice(0, 10)
  }, [filteredEvents])

  // Event click is handled via Schedule-X callbacks.onEventClick in useCalendarApp config above

  // Quick complete reminder
  const handleQuickComplete = async (eventId: string, e: React.MouseEvent) => {
    e.stopPropagation()

    const [type, id] = eventId.split('-')
    if (type !== 'reminder') return

    const event = events.find(ev => ev.id === eventId)
    if (!event) return

    try {
      await api.post(`/vehicles/${event.vehicle_vin}/reminders/${id}/done`)
      toast.success(t('calendar.reminderDone'))
      loadEvents()
    } catch {
      toast.error(t('calendar.completeReminderError'))
    }
  }

  // Phase 3: Export calendar to iCal
  const handleExportCalendar = () => {
    const params = new URLSearchParams()

    if (selectedVehicles.length > 0) {
      params.set('vehicle_vins', selectedVehicles.join(','))
    }

    const types = showHistory ? [...selectedTypes, 'service'] : selectedTypes
    if (types.length > 0) {
      params.set('event_types', types.join(','))
    }

    window.location.href = `/api/calendar/export?${params.toString()}`
    toast.success(t('calendar.exportStarted'))
  }

  // Phase 3: Toggle event selection for bulk actions
  const toggleEventSelection = (eventId: string) => {
    setSelectedEvents(prev =>
      prev.includes(eventId)
        ? prev.filter(id => id !== eventId)
        : [...prev, eventId]
    )
  }

  // Phase 3: Bulk complete selected reminder items
  const handleBulkComplete = async () => {
    const reminderIds = selectedEvents
      .filter(id => id.startsWith('reminder-'))
      .map(id => id.split('-')[1])

    if (reminderIds.length === 0) {
      toast.error(t('calendar.noRemindersSelected'))
      return
    }

    setBulkCompleting(true)
    try {
      let completed = 0
      let failed = 0
      const errors: string[] = []

      for (const id of reminderIds) {
        const event = events.find(e => e.id === `reminder-${id}`)
        if (!event || event.is_completed) continue

        try {
          await api.post(`/vehicles/${event.vehicle_vin}/reminders/${id}/done`)
          completed++
        } catch (err: unknown) {
          failed++
          const error = err as { response?: { data?: { detail?: string } }; message?: string }
          const errorMessage = error.response?.data?.detail || error.message || 'Network error'
          errors.push(`${event.title}: ${errorMessage}`)
        }
      }

      // Clear selection and exit bulk mode
      setSelectedEvents([])
      setBulkMode(false)
      loadEvents()

      // Show appropriate toast message
      if (completed > 0 && failed === 0) {
        toast.success(`Completed ${completed} item(s)`)
      } else if (completed > 0 && failed > 0) {
        toast.warning(`Completed ${completed} item(s), failed ${failed}`, {
          description: errors.slice(0, 3).join(', ')
        })
      } else {
        toast.error(`Failed to complete ${failed} item(s)`, {
          description: errors.slice(0, 3).join(', ')
        })
      }
    } catch {
      toast.error(t('calendar.completeMaintenanceError'))
    } finally {
      setBulkCompleting(false)
    }
  }

  // Phase 3: Show notes modal
  const handleShowNotes = (event: CalendarEvent, e: React.MouseEvent) => {
    e.stopPropagation()
    setSelectedEventForNotes(event)
    setShowNotesModal(true)
  }

  // Event styling is handled via Schedule-X calendars config (per-type colors defined in EVENT_CALENDARS)

  // Toggle vehicle filter
  const toggleVehicle = (vin: string) => {
    setSelectedVehicles(prev =>
      prev.includes(vin) ? prev.filter(v => v !== vin) : [...prev, vin]
    )
  }

  // Toggle event type filter
  const toggleEventType = (type: string) => {
    setSelectedTypes(prev =>
      prev.includes(type) ? prev.filter(t => t !== type) : [...prev, type]
    )
  }

  // Format date for display
  const formatDate = (dateStr: string) => {
    return format(new Date(dateStr), 'MMM d, yyyy')
  }

  // Get days until/since event
  const getDaysUntil = (dateStr: string) => {
    const days = differenceInDays(new Date(dateStr), new Date())
    if (days < 0) return `${Math.abs(days)} days ago`
    if (days === 0) return 'Today'
    if (days === 1) return 'Tomorrow'
    return `in ${days} days`
  }

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-3xl font-bold mb-2 text-garage-text">{t('calendar.title')}</h1>
        <p className="text-garage-text-muted">
          {t('calendar.subtitle')}
        </p>
      </div>

      <div className="mb-6">
        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <CalendarIcon className="w-5 h-5 text-garage-text-muted" />
              <span className="text-sm text-garage-text-muted">{t('calendar.totalEvents')}</span>
            </div>
            <p className="text-2xl font-bold text-garage-text">{summary.total}</p>
          </div>

          <div className={`bg-garage-surface border rounded-lg p-4 ${
            summary.overdue > 0 ? 'border-danger' : 'border-garage-border'
          }`}>
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className={`w-5 h-5 ${summary.overdue > 0 ? 'text-danger' : 'text-garage-text-secondary'}`} />
              <span className={`text-sm ${summary.overdue > 0 ? 'text-danger' : 'text-garage-text-secondary'}`}>{t('calendar.overdue')}</span>
            </div>
            <p className={`text-2xl font-bold ${summary.overdue > 0 ? 'text-danger' : 'text-garage-text'}`}>{summary.overdue}</p>
          </div>

          <div className="bg-garage-surface border border-warning rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-5 h-5 text-warning" />
              <span className="text-sm text-warning">{t('calendar.next7Days')}</span>
            </div>
            <p className="text-2xl font-bold text-warning">{summary.upcoming_7_days}</p>
          </div>

          <div className="bg-garage-surface border border-primary rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-5 h-5 text-primary" />
              <span className="text-sm text-primary">{t('calendar.next30Days')}</span>
            </div>
            <p className="text-2xl font-bold text-primary">{summary.upcoming_30_days}</p>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-4 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Filter className="w-5 h-5 text-primary" />
              <h2 className="text-lg font-semibold text-garage-text">{t('calendar.filtersActions')}</h2>
            </div>

            {/* Phase 3: Action Buttons */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setBulkMode(!bulkMode)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                  bulkMode
                    ? 'bg-primary text-white'
                    : 'bg-garage-bg text-garage-text-muted border border-garage-border hover:border-primary'
                }`}
              >
                {bulkMode ? <CheckSquare className="w-4 h-4" /> : <Square className="w-4 h-4" />}
                <span className="hidden sm:inline">{t('calendar.bulkMode')}</span>
              </button>

              <button
                onClick={handleExportCalendar}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-garage-bg text-garage-text-muted border border-garage-border hover:border-primary transition-colors"
              >
                <Download className="w-4 h-4" />
                <span className="hidden sm:inline">{t('calendar.exportICal')}</span>
              </button>
            </div>
          </div>

          {/* Phase 3: Search Bar */}
          <div className="mb-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-garage-text-muted" />
              <input
                type="text"
                placeholder={t('calendar.searchPlaceholder')}
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-10 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text placeholder-garage-text-muted focus:outline-none focus:border-primary"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-garage-text-muted hover:text-garage-text"
                >
                  <X className="w-5 h-5" />
                </button>
              )}
            </div>
            {searchQuery && (
              <p className="text-sm text-garage-text-muted mt-2">
                Found {filteredEvents.length} event(s) matching "{searchQuery}"
              </p>
            )}
          </div>

          {/* Phase 3: Bulk Actions Bar */}
          {bulkMode && (
            <div className="mb-4 p-3 bg-primary/10 border border-primary rounded-lg">
              <div className="flex items-center justify-between">
                <span className="text-sm text-garage-text">
                  {selectedEvents.length} event(s) selected
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleBulkComplete}
                    disabled={selectedEvents.length === 0 || bulkCompleting}
                    className="px-3 py-1 rounded-lg text-sm bg-success text-white hover:bg-success-dark disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                    {bulkCompleting ? t('calendar.completing') : t('calendar.completeSelected')}
                  </button>
                  <button
                    onClick={() => setSelectedEvents([])}
                    className="px-3 py-1 rounded-lg text-sm bg-garage-bg text-garage-text-muted border border-garage-border hover:border-danger transition-colors"
                  >
                    Clear
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Vehicle Filter */}
            <div>
              <h3 className="text-sm font-medium text-garage-text-muted mb-2">{t('calendar.vehicles')}</h3>
              <div className="flex flex-wrap gap-2">
                {vehicles.map(vehicle => (
                  <button
                    key={vehicle.vin}
                    onClick={() => toggleVehicle(vehicle.vin)}
                    className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                      selectedVehicles.length === 0 || selectedVehicles.includes(vehicle.vin)
                        ? 'bg-primary text-white'
                        : 'bg-garage-bg text-garage-text-muted border border-garage-border'
                    }`}
                  >
                    {vehicle.nickname}
                  </button>
                ))}
                {vehicles.length === 0 && (
                  <p className="text-garage-text-muted text-sm">{t('calendar.noVehiclesFound')}</p>
                )}
              </div>
            </div>

            {/* Event Type Filter */}
            <div>
              <h3 className="text-sm font-medium text-garage-text-muted mb-2">{t('calendar.eventTypes')}</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => toggleEventType('maintenance')}
                  className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                    selectedTypes.includes('maintenance')
                      ? 'bg-blue-600 text-white'
                      : 'bg-garage-bg text-garage-text-muted border border-garage-border'
                  }`}
                >
                  Maintenance
                </button>
                <button
                  onClick={() => toggleEventType('insurance')}
                  className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                    selectedTypes.includes('insurance')
                      ? 'bg-red-600 text-white'
                      : 'bg-garage-bg text-garage-text-muted border border-garage-border'
                  }`}
                >
                  Insurance
                </button>
                <button
                  onClick={() => toggleEventType('warranty')}
                  className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                    selectedTypes.includes('warranty')
                      ? 'bg-amber-600 text-white'
                      : 'bg-garage-bg text-garage-text-muted border border-garage-border'
                  }`}
                >
                  Warranties
                </button>
                <button
                  onClick={() => setShowHistory(!showHistory)}
                  className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                    showHistory
                      ? 'bg-gray-600 text-white'
                      : 'bg-garage-bg text-garage-text-muted border border-garage-border'
                  }`}
                >
                  <Wrench className="w-4 h-4 inline mr-1" />
                  Service History
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Calendar */}
          <div className="lg:col-span-2 bg-garage-surface border border-garage-border rounded-lg p-4 relative">
            <div className="sx-calendar-wrapper" style={{ height: 600 }}>
              <ScheduleXCalendar calendarApp={calendar} />
            </div>
            {loading && (
              <div className="absolute inset-0 bg-garage-bg/50 backdrop-blur-xs flex items-center justify-center rounded-lg">
                <div className="text-garage-text-muted">Loading...</div>
              </div>
            )}
          </div>

          {/* Upcoming Events Sidebar */}
          <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
            <h3 className="text-lg font-semibold text-garage-text mb-4">{t('calendar.upcomingEvents')}</h3>

            {upcomingEvents.length === 0 ? (
              <p className="text-garage-text-muted text-sm text-center py-8">
                {t('calendar.noUpcomingEvents')}
              </p>
            ) : (
              <div className="space-y-3">
                {upcomingEvents.map(event => (
                  <div
                    key={event.id}
                    onClick={() => {
                      if (bulkMode) {
                        toggleEventSelection(event.id)
                      } else {
                        const [type] = event.id.split('-')
                        const tab = type === 'maintenance' ? 'maintenance' : type === 'insurance' ? 'insurance' : type === 'warranty' ? 'warranties' : 'service'
                        navigate(`/vehicles/${event.vehicle_vin}?tab=${tab}`)
                      }
                    }}
                    className={`p-3 rounded-lg border cursor-pointer transition-colors hover:border-primary ${
                      event.urgency === 'overdue'
                        ? 'border-danger bg-danger/5'
                        : event.urgency === 'high'
                        ? 'border-warning bg-warning/5'
                        : 'border-garage-border'
                    } ${bulkMode && selectedEvents.includes(event.id) ? 'ring-2 ring-primary' : ''}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      {/* Phase 3: Bulk selection checkbox */}
                      {bulkMode && (
                        <div className="flex items-center pt-1">
                          {selectedEvents.includes(event.id) ? (
                            <CheckSquare className="w-5 h-5 text-primary" />
                          ) : (
                            <Square className="w-5 h-5 text-garage-text-muted" />
                          )}
                        </div>
                      )}

                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          {event.is_recurring && <RotateCw className="w-3 h-3 text-primary" />}
                          {/* Phase 3: Estimated badge */}
                          {event.is_estimated && (
                            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-500">
                              <Gauge className="w-3 h-3" />
                              EST
                            </span>
                          )}
                          {/* Phase 3: Mileage badge */}
                          {event.due_mileage_km && (
                            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-500">
                              <Gauge className="w-3 h-3" />
                              {UnitFormatter.formatDistance(parseFloat(event.due_mileage_km), system)}
                            </span>
                          )}
                          <span className={`text-xs font-medium ${
                            event.type === 'insurance' ? 'text-red-500' :
                            event.type === 'warranty' ? 'text-amber-500' :
                            'text-blue-500'
                          }`}>
                            {event.type.toUpperCase()}
                          </span>
                        </div>
                        <p className="text-sm font-medium text-garage-text mb-1">{event.title}</p>
                        <p className="text-xs text-garage-text-muted">{event.vehicle_nickname}</p>
                        <p className="text-xs text-garage-text-muted mt-1">
                          {formatDate(event.date)} • {getDaysUntil(event.date)}
                        </p>
                        {/* Maintenance detail fields */}
                        {event.type === 'maintenance' && (event.status || event.km_until_due != null) && (
                          <div className="flex flex-wrap gap-1.5 mt-1.5">
                            {event.status && (
                              <span className={`text-xs px-1.5 py-0.5 rounded ${
                                event.status === 'overdue' ? 'bg-danger/20 text-danger' :
                                event.status === 'due_soon' ? 'bg-warning/20 text-warning' :
                                event.status === 'never_performed' ? 'bg-purple-500/20 text-purple-400' :
                                'bg-success/20 text-success'
                              }`}>
                                {event.status === 'due_soon' ? 'Due Soon' :
                                 event.status === 'never_performed' ? 'Never Done' :
                                 event.status === 'overdue' ? 'Overdue' : 'On Track'}
                              </span>
                            )}
                            {(() => {
                              if (event.km_until_due == null) return null
                              const km = parseFloat(event.km_until_due)
                              if (isNaN(km)) return null
                              const distanceUnit = UnitFormatter.getDistanceUnit(system)
                              // 500 mi ≈ 805 km warning threshold; convert to display unit for thresholds.
                              const warnThresholdInDisplay = 500
                              const displayValue = system === 'imperial' ? (UnitConverter.kmToMiles(km) ?? 0) : km
                              return (
                                <span className={`text-xs px-1.5 py-0.5 rounded ${
                                  displayValue <= 0 ? 'bg-danger/20 text-danger' :
                                  displayValue <= warnThresholdInDisplay ? 'bg-warning/20 text-warning' :
                                  'bg-garage-bg text-garage-text-muted'
                                }`}>
                                  {displayValue <= 0
                                    ? `${Math.abs(displayValue).toLocaleString()} ${distanceUnit} over`
                                    : `${displayValue.toLocaleString()} ${distanceUnit} left`}
                                </span>
                              )
                            })()}
                          </div>
                        )}
                      </div>

                      {!bulkMode && (
                        <div className="flex items-center gap-1">
                          {/* Phase 3: Notes button */}
                          {event.notes && (
                            <button
                              onClick={(e) => handleShowNotes(event, e)}
                              className="p-1 hover:bg-primary/20 rounded transition-colors"
                              title="View notes"
                            >
                              <MessageCircle className="w-4 h-4 text-primary" />
                            </button>
                          )}
                          {/* Quick complete button */}
                          {event.type === 'maintenance' && !event.is_completed && (
                            <button
                              onClick={(e) => handleQuickComplete(event.id, e)}
                              className="p-1 hover:bg-success/20 rounded transition-colors"
                              title="Mark complete"
                            >
                              <CheckCircle className="w-5 h-5 text-success" />
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Legend */}
        <div className="mt-6 bg-garage-surface border border-garage-border rounded-lg p-4">
          <h3 className="text-sm font-medium text-garage-text mb-3">{t('calendar.legend')}</h3>
          <div className="flex flex-wrap gap-4">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-blue-600 rounded"></div>
              <span className="text-sm text-garage-text">Maintenance Schedule</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-red-600 rounded"></div>
              <span className="text-sm text-garage-text">Insurance Renewals</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-amber-600 rounded"></div>
              <span className="text-sm text-garage-text">Warranty Expirations</span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-gray-600 rounded opacity-60"></div>
              <span className="text-sm text-garage-text">Service History</span>
            </div>
            <div className="flex items-center gap-2">
              <RotateCw className="w-4 h-4 text-primary" />
              <span className="text-sm text-garage-text">Recurring Event</span>
            </div>
            {/* Phase 3: New legend items */}
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-500">
                <Gauge className="w-3 h-3" />
                EST
              </span>
              <span className="text-sm text-garage-text">Estimated from Mileage</span>
            </div>
            <div className="flex items-center gap-2">
              <MessageCircle className="w-4 h-4 text-primary" />
              <span className="text-sm text-garage-text">Has Notes</span>
            </div>
          </div>
        </div>
      </div>

      {/* Phase 3: Notes Modal */}
      {showNotesModal && selectedEventForNotes && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-garage-surface border border-garage-border rounded-lg max-w-2xl w-full max-h-[80vh] overflow-auto">
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-bold text-garage-text">{t('calendar.eventNotes')}</h3>
                <button
                  onClick={() => setShowNotesModal(false)}
                  className="p-1 hover:bg-garage-bg rounded transition-colors"
                >
                  <X className="w-5 h-5 text-garage-text-muted" />
                </button>
              </div>

              <div className="space-y-4">
                {/* Event details */}
                <div>
                  <h4 className="text-sm font-medium text-garage-text-muted mb-2">Event</h4>
                  <div className="bg-garage-bg border border-garage-border rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`text-xs font-medium px-2 py-1 rounded ${
                        selectedEventForNotes.type === 'insurance' ? 'bg-red-500/20 text-red-500' :
                        selectedEventForNotes.type === 'warranty' ? 'bg-amber-500/20 text-amber-500' :
                        'bg-blue-500/20 text-blue-500'
                      }`}>
                        {selectedEventForNotes.type.toUpperCase()}
                      </span>
                      {selectedEventForNotes.is_recurring && (
                        <RotateCw className="w-3 h-3 text-primary" />
                      )}
                      {selectedEventForNotes.is_estimated && (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-500">
                          <Gauge className="w-3 h-3" />
                          EST
                        </span>
                      )}
                    </div>
                    <p className="text-lg font-medium text-garage-text mb-1">
                      {selectedEventForNotes.title}
                    </p>
                    <p className="text-sm text-garage-text-muted">
                      {selectedEventForNotes.vehicle_nickname} • {formatDate(selectedEventForNotes.date)}
                    </p>
                    {selectedEventForNotes.due_mileage_km && (
                      <p className="text-sm text-garage-text-muted mt-2">
                        Due at: {UnitFormatter.formatDistance(parseFloat(selectedEventForNotes.due_mileage_km), system)}
                      </p>
                    )}
                  </div>
                </div>

                {/* Notes content */}
                <div>
                  <h4 className="text-sm font-medium text-garage-text-muted mb-2">Notes</h4>
                  <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                    <p className="text-garage-text whitespace-pre-wrap">
                      {selectedEventForNotes.notes || 'No notes available'}
                    </p>
                  </div>
                </div>

                {selectedEventForNotes.description && (
                  <div>
                    <h4 className="text-sm font-medium text-garage-text-muted mb-2">Description</h4>
                    <div className="bg-garage-bg border border-garage-border rounded-lg p-4">
                      <p className="text-garage-text whitespace-pre-wrap">
                        {selectedEventForNotes.description}
                      </p>
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-6 flex justify-end">
                <button
                  onClick={() => setShowNotesModal(false)}
                  className="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
