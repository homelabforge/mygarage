import { useState, useEffect, useCallback, useMemo } from 'react'
import { Calendar as CalendarIcon, Filter, AlertCircle, CheckCircle, RotateCw, Clock, Wrench, Search, Download, Gauge, X, CheckSquare, Square, MessageCircle } from 'lucide-react'
import { Calendar as BigCalendar, dateFnsLocalizer, View } from 'react-big-calendar'
import { format, parse, startOfWeek, getDay, startOfMonth, endOfMonth, subMonths, addMonths, startOfDay, endOfDay, addDays, differenceInDays, isBefore, isAfter } from 'date-fns'
import { enUS } from 'date-fns/locale'
import { toast } from 'sonner'
import { useNavigate } from 'react-router-dom'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import type { CalendarEvent, CalendarResponse } from '../types/calendar'
import type { Vehicle } from '../types/vehicle'
import api from '../services/api'

// date-fns localizer for react-big-calendar
const locales = {
  'en-US': enUS,
}

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek,
  getDay,
  locales,
})

// Define event type for react-big-calendar
interface BigCalendarEvent {
  id: string
  title: string
  start: Date
  end: Date
  resource: CalendarEvent
}

export default function CalendarPage() {
  const navigate = useNavigate()
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [summary, setSummary] = useState({ total: 0, overdue: 0, upcoming_7_days: 0, upcoming_30_days: 0 })
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedVehicles, setSelectedVehicles] = useState<string[]>([])
  const [selectedTypes, setSelectedTypes] = useState<string[]>(['reminder', 'insurance', 'warranty'])
  const [showHistory, setShowHistory] = useState(false)
  const [view, setView] = useState<View>('month')
  const [date, setDate] = useState(new Date())

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
      toast.error('Failed to load vehicles')
    }
  }, [])

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
      toast.error('Failed to load calendar events')
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [date, selectedVehicles, selectedTypes, showHistory])

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

  // Convert CalendarEvents to BigCalendar format (use filtered events for search)
  const bigCalendarEvents: BigCalendarEvent[] = useMemo(() => {
    return filteredEvents.map(event => {
      const eventDate = new Date(event.date)
      return {
        id: event.id,
        title: event.title,
        start: eventDate,
        end: eventDate,
        resource: event,
      }
    })
  }, [filteredEvents])

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

  // Handle event click
  const handleEventClick = (event: BigCalendarEvent) => {
    const calendarEvent = event.resource
    const [type] = calendarEvent.id.split('-')

    // Navigate to appropriate detail page
    switch (type) {
      case 'reminder':
        navigate(`/vehicles/${calendarEvent.vehicle_vin}?tab=reminders`)
        break
      case 'insurance':
        navigate(`/vehicles/${calendarEvent.vehicle_vin}?tab=insurance`)
        break
      case 'warranty':
        navigate(`/vehicles/${calendarEvent.vehicle_vin}?tab=warranties`)
        break
      case 'service':
        navigate(`/vehicles/${calendarEvent.vehicle_vin}?tab=service`)
        break
    }
  }

  // Quick complete reminder
  const handleQuickComplete = async (eventId: string, e: React.MouseEvent) => {
    e.stopPropagation()

    const [type, id] = eventId.split('-')
    if (type !== 'reminder') return

    const event = events.find(ev => ev.id === eventId)
    if (!event) return

    try {
      await api.post(`/vehicles/${event.vehicle_vin}/reminders/${id}/complete`)
      toast.success('Reminder marked as complete')
      loadEvents()
    } catch {
      toast.error('Failed to complete reminder')
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
    toast.success('Calendar export started')
  }

  // Phase 3: Toggle event selection for bulk actions
  const toggleEventSelection = (eventId: string) => {
    setSelectedEvents(prev =>
      prev.includes(eventId)
        ? prev.filter(id => id !== eventId)
        : [...prev, eventId]
    )
  }

  // Phase 3: Bulk complete selected reminders
  const handleBulkComplete = async () => {
    const reminderIds = selectedEvents
      .filter(id => id.startsWith('reminder-'))
      .map(id => id.split('-')[1])

    if (reminderIds.length === 0) {
      toast.error('No reminders selected')
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
          await api.post(`/vehicles/${event.vehicle_vin}/reminders/${id}/complete`)
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
        toast.success(`Completed ${completed} reminder(s)`)
      } else if (completed > 0 && failed > 0) {
        toast.warning(`Completed ${completed} reminder(s), failed ${failed}`, {
          description: errors.slice(0, 3).join(', ')
        })
      } else {
        toast.error(`Failed to complete ${failed} reminder(s)`, {
          description: errors.slice(0, 3).join(', ')
        })
      }
    } catch {
      toast.error('Failed to complete reminders')
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

  // Custom event style getter
  const eventStyleGetter = (event: BigCalendarEvent) => {
    const calendarEvent = event.resource
    let backgroundColor = '#3b82f6' // default blue
    let borderColor = '#3b82f6'

    // Color by type
    switch (calendarEvent.type) {
      case 'insurance':
        backgroundColor = '#ef4444' // red
        borderColor = '#ef4444'
        break
      case 'warranty':
        backgroundColor = '#f59e0b' // amber
        borderColor = '#f59e0b'
        break
      case 'reminder':
        backgroundColor = '#3b82f6' // blue
        borderColor = '#3b82f6'
        break
      case 'service':
        backgroundColor = '#6b7280' // gray (muted)
        borderColor = '#6b7280'
        break
    }

    // Add urgency indicator
    if (calendarEvent.urgency === 'overdue') {
      borderColor = '#dc2626' // darker red border
    }

    return {
      style: {
        backgroundColor,
        borderLeft: `4px solid ${borderColor}`,
        color: '#fff',
        borderRadius: '4px',
        opacity: calendarEvent.is_completed ? 0.5 : calendarEvent.urgency === 'historical' ? 0.6 : 1,
      }
    }
  }

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
        <h1 className="text-3xl font-bold mb-2 text-garage-text">Calendar</h1>
        <p className="text-garage-text-muted">
          View all upcoming maintenance, insurance renewals, and warranty expirations
        </p>
      </div>

      <div className="mb-6">
        {/* Summary Stats */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <CalendarIcon className="w-5 h-5 text-garage-text-muted" />
              <span className="text-sm text-garage-text-muted">Total Events</span>
            </div>
            <p className="text-2xl font-bold text-garage-text">{summary.total}</p>
          </div>

          <div className={`bg-garage-surface border rounded-lg p-4 ${
            summary.overdue > 0 ? 'border-danger' : 'border-garage-border'
          }`}>
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className={`w-5 h-5 ${summary.overdue > 0 ? 'text-danger' : 'text-garage-text-secondary'}`} />
              <span className={`text-sm ${summary.overdue > 0 ? 'text-danger' : 'text-garage-text-secondary'}`}>Overdue</span>
            </div>
            <p className={`text-2xl font-bold ${summary.overdue > 0 ? 'text-danger' : 'text-garage-text'}`}>{summary.overdue}</p>
          </div>

          <div className="bg-garage-surface border border-warning rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-5 h-5 text-warning" />
              <span className="text-sm text-warning">Next 7 Days</span>
            </div>
            <p className="text-2xl font-bold text-warning">{summary.upcoming_7_days}</p>
          </div>

          <div className="bg-garage-surface border border-primary rounded-lg p-4">
            <div className="flex items-center gap-2 mb-2">
              <Clock className="w-5 h-5 text-primary" />
              <span className="text-sm text-primary">Next 30 Days</span>
            </div>
            <p className="text-2xl font-bold text-primary">{summary.upcoming_30_days}</p>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-garage-surface border border-garage-border rounded-lg p-4 mb-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Filter className="w-5 h-5 text-primary" />
              <h2 className="text-lg font-semibold text-garage-text">Filters & Actions</h2>
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
                <span className="hidden sm:inline">Bulk Mode</span>
              </button>

              <button
                onClick={handleExportCalendar}
                className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm bg-garage-bg text-garage-text-muted border border-garage-border hover:border-primary transition-colors"
              >
                <Download className="w-4 h-4" />
                <span className="hidden sm:inline">Export iCal</span>
              </button>
            </div>
          </div>

          {/* Phase 3: Search Bar */}
          <div className="mb-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-garage-text-muted" />
              <input
                type="text"
                placeholder="Search events by title, description, or vehicle..."
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
                    {bulkCompleting ? 'Completing...' : 'Complete Selected'}
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
              <h3 className="text-sm font-medium text-garage-text-muted mb-2">Vehicles</h3>
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
                  <p className="text-garage-text-muted text-sm">No vehicles found</p>
                )}
              </div>
            </div>

            {/* Event Type Filter */}
            <div>
              <h3 className="text-sm font-medium text-garage-text-muted mb-2">Event Types</h3>
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => toggleEventType('reminder')}
                  className={`px-3 py-1 rounded-lg text-sm transition-colors ${
                    selectedTypes.includes('reminder')
                      ? 'bg-blue-600 text-white'
                      : 'bg-garage-bg text-garage-text-muted border border-garage-border'
                  }`}
                >
                  Reminders
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
            <div className="calendar-container" style={{ height: 600 }}>
              <BigCalendar
                localizer={localizer}
                events={bigCalendarEvents}
                startAccessor="start"
                endAccessor="end"
                view={view}
                onView={setView}
                date={date}
                onNavigate={setDate}
                onSelectEvent={handleEventClick}
                eventPropGetter={eventStyleGetter}
                popup
                views={['month', 'week', 'day', 'agenda']}
                style={{ height: '100%' }}
              />
            </div>
            {loading && (
              <div className="absolute inset-0 bg-garage-bg/50 backdrop-blur-xs flex items-center justify-center rounded-lg">
                <div className="text-garage-text-muted">Loading...</div>
              </div>
            )}
          </div>

          {/* Upcoming Events Sidebar */}
          <div className="bg-garage-surface border border-garage-border rounded-lg p-4">
            <h3 className="text-lg font-semibold text-garage-text mb-4">Upcoming Events</h3>

            {upcomingEvents.length === 0 ? (
              <p className="text-garage-text-muted text-sm text-center py-8">
                No upcoming events in the next 30 days
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
                        const tab = type === 'reminder' ? 'reminders' : type === 'insurance' ? 'insurance' : type === 'warranty' ? 'warranties' : 'service'
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
                          {event.due_mileage && (
                            <span className="flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-blue-500/20 text-blue-500">
                              <Gauge className="w-3 h-3" />
                              {event.due_mileage.toLocaleString()} mi
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
                          {event.type === 'reminder' && !event.is_completed && (
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
          <h3 className="text-sm font-medium text-garage-text mb-3">Legend</h3>
          <div className="flex flex-wrap gap-4">
            <div className="flex items-center gap-2">
              <div className="w-4 h-4 bg-blue-600 rounded"></div>
              <span className="text-sm text-garage-text">Maintenance Reminders</span>
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
                <h3 className="text-xl font-bold text-garage-text">Event Notes</h3>
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
                    {selectedEventForNotes.due_mileage && (
                      <p className="text-sm text-garage-text-muted mt-2">
                        Due at: {selectedEventForNotes.due_mileage.toLocaleString()} miles
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
