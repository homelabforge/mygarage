import { useState, useEffect } from 'react'
import ReminderList from '../ReminderList'
import ReminderForm from '../ReminderForm'
import MaintenanceTemplatePanel from '../MaintenanceTemplatePanel'
import type { Reminder } from '../../types/reminder'
import type { Vehicle } from '../../types/vehicle'
import api from '../../services/api'

interface RemindersTabProps {
  vin: string
}

export default function RemindersTab({ vin }: RemindersTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingReminder, setEditingReminder] = useState<Reminder | undefined>(undefined)
  const [refreshKey, setRefreshKey] = useState(0)
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)

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
  }, [vin])

  const handleFormSuccess = () => {
    setRefreshKey(prev => prev + 1)
  }

  const handleAddClick = () => {
    setEditingReminder(undefined)
    setShowForm(true)
  }

  const handleEditClick = (reminder: Reminder) => {
    setEditingReminder(reminder)
    setShowForm(true)
  }

  const handleCloseForm = () => {
    setShowForm(false)
    setEditingReminder(undefined)
  }

  return (
    <div className="space-y-6">
      <MaintenanceTemplatePanel vin={vin} vehicle={vehicle || undefined} />

      <ReminderList
        key={refreshKey}
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
      />

      {showForm && (
        <ReminderForm
          vin={vin}
          reminder={editingReminder}
          onSuccess={handleFormSuccess}
          onClose={handleCloseForm}
        />
      )}
    </div>
  )
}
