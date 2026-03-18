import { useState, useEffect } from 'react'
import ServiceVisitList from '../ServiceVisitList'
import ServiceVisitForm from '../ServiceVisitForm'
import type { ServiceVisit } from '../../types/serviceVisit'
import type { Vehicle } from '../../types/vehicle'
import api from '../../services/api'

interface ServiceTabProps {
  vin: string
}

export default function ServiceTab({ vin }: ServiceTabProps) {
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [vehicleReady, setVehicleReady] = useState(false)
  const [showVisitForm, setShowVisitForm] = useState(false)
  const [editVisit, setEditVisit] = useState<ServiceVisit | undefined>()
  const [visitRefreshKey, setVisitRefreshKey] = useState(0)

  useEffect(() => {
    setVehicleReady(false)
    const fetchVehicle = async () => {
      try {
        const response = await api.get(`/vehicles/${vin}`)
        setVehicle(response.data)
      } catch (err) {
        console.error('Failed to fetch vehicle:', err)
      } finally {
        setVehicleReady(true)
      }
    }
    fetchVehicle()
  }, [vin])

  const handleAddVisit = () => {
    setEditVisit(undefined)
    setShowVisitForm(true)
  }

  const handleEditVisit = (visit: ServiceVisit) => {
    setEditVisit(visit)
    setShowVisitForm(true)
  }

  const handleVisitFormClose = () => {
    setShowVisitForm(false)
    setEditVisit(undefined)
  }

  const handleVisitSuccess = () => {
    setVisitRefreshKey((k) => k + 1)
    handleVisitFormClose()
  }

  return (
    <div className="space-y-8">
      <ServiceVisitList
        vin={vin}
        onAddClick={handleAddVisit}
        onEditClick={handleEditVisit}
        refreshTrigger={visitRefreshKey}
      />

      {showVisitForm && !vehicleReady && (
        <div className="fixed inset-0 modal-overlay backdrop-blur-xs flex items-center justify-center z-50">
          <div className="bg-garage-surface rounded-lg border border-garage-border p-8">
            <div className="text-garage-text-muted text-sm">Loading...</div>
          </div>
        </div>
      )}
      {showVisitForm && vehicleReady && (
        <ServiceVisitForm
          vin={vin}
          vehicleType={vehicle?.vehicle_type}
          visit={editVisit}
          onClose={handleVisitFormClose}
          onSuccess={handleVisitSuccess}
        />
      )}
    </div>
  )
}
