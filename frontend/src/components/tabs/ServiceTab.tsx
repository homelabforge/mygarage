import { useState, useEffect } from 'react'
import { CalendarClock, X } from 'lucide-react'
import ServiceVisitList from '../ServiceVisitList'
import ServiceVisitForm from '../ServiceVisitForm'
import MaintenanceSchedule from '../MaintenanceSchedule'
import MaintenanceTemplatePanel from '../MaintenanceTemplatePanel'
import type { ServiceVisit } from '../../types/serviceVisit'
import type { MaintenanceScheduleItem } from '../../types/maintenanceSchedule'
import type { Vehicle } from '../../types/vehicle'
import api from '../../services/api'

interface ServiceTabProps {
  vin: string
}

export default function ServiceTab({ vin }: ServiceTabProps) {
  // Vehicle state for templates
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)

  // Service visit state
  const [showVisitForm, setShowVisitForm] = useState(false)
  const [editVisit, setEditVisit] = useState<ServiceVisit | undefined>()
  const [preselectedScheduleItem, setPreselectedScheduleItem] = useState<MaintenanceScheduleItem | undefined>()
  const [visitRefreshKey, setVisitRefreshKey] = useState(0)

  // Maintenance schedule modal state
  const [showScheduleModal, setShowScheduleModal] = useState(false)
  const [scheduleRefreshKey, setScheduleRefreshKey] = useState(0)

  // Fetch vehicle for template panel
  useEffect(() => {
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        setVehicle(response.data)
      } catch (err) {
        console.error('Failed to fetch vehicle:', err)
      }
    }
    fetchVehicle()

    // Listen for template-applied event to refresh schedule
    const handleTemplateRefresh = () => {
      setScheduleRefreshKey((prev) => prev + 1)
    }
    window.addEventListener('reminders-refresh', handleTemplateRefresh)

    return () => {
      window.removeEventListener('reminders-refresh', handleTemplateRefresh)
    }
  }, [vin])

  // Service visit handlers
  const handleAddVisit = () => {
    setEditVisit(undefined)
    setPreselectedScheduleItem(undefined)
    setShowVisitForm(true)
  }

  const handleEditVisit = (visit: ServiceVisit) => {
    setEditVisit(visit)
    setPreselectedScheduleItem(undefined)
    setShowVisitForm(true)
  }

  const handleLogService = (scheduleItem: MaintenanceScheduleItem) => {
    setEditVisit(undefined)
    setPreselectedScheduleItem(scheduleItem)
    setShowVisitForm(true)
    setShowScheduleModal(false) // Close schedule modal when logging
  }

  const handleVisitFormClose = () => {
    setShowVisitForm(false)
    setEditVisit(undefined)
    setPreselectedScheduleItem(undefined)
  }

  const handleVisitSuccess = () => {
    setVisitRefreshKey((k) => k + 1)
    handleVisitFormClose()
  }

  return (
    <div className="space-y-8">
      {/* Maintenance Schedule Button */}
      <div className="flex justify-end">
        <button
          onClick={() => setShowScheduleModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-primary/10 text-primary border border-primary/30 rounded-lg hover:bg-primary/20 transition-colors"
        >
          <CalendarClock className="w-5 h-5" />
          <span>Maintenance Schedule</span>
        </button>
      </div>

      {/* Service History Section */}
      <ServiceVisitList
        vin={vin}
        onAddClick={handleAddVisit}
        onEditClick={handleEditVisit}
        refreshTrigger={visitRefreshKey}
      />

      {/* Service Visit Form Modal */}
      {showVisitForm && (
        <ServiceVisitForm
          vin={vin}
          visit={editVisit}
          preselectedScheduleItem={preselectedScheduleItem}
          onClose={handleVisitFormClose}
          onSuccess={handleVisitSuccess}
        />
      )}

      {/* Maintenance Schedule Modal */}
      {showScheduleModal && (
        <div className="fixed inset-0 modal-overlay backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-garage-surface rounded-lg border border-garage-border w-full max-w-5xl max-h-[90vh] flex flex-col">
            {/* Modal Header */}
            <div className="sticky top-0 bg-garage-surface border-b border-garage-border px-6 py-4 flex items-center justify-between rounded-t-lg">
              <div className="flex items-center gap-2">
                <CalendarClock className="w-5 h-5 text-primary" />
                <h2 className="text-xl font-semibold text-garage-text">Maintenance Schedule</h2>
              </div>
              <button
                onClick={() => setShowScheduleModal(false)}
                className="text-garage-text-muted hover:text-garage-text transition-colors"
              >
                <X size={24} />
              </button>
            </div>

            {/* Modal Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Templates Panel */}
              <MaintenanceTemplatePanel vin={vin} vehicle={vehicle || undefined} />

              {/* Schedule Items */}
              <MaintenanceSchedule
                vin={vin}
                onLogService={handleLogService}
                key={`schedule-${visitRefreshKey}-${scheduleRefreshKey}`}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
