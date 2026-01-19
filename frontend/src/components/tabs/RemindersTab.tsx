import { useState } from 'react'
import ReminderList from '../ReminderList'
import ReminderForm from '../ReminderForm'
import type { Reminder } from '../../types/reminder'

interface RemindersTabProps {
  vin: string
}

export default function RemindersTab({ vin }: RemindersTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingReminder, setEditingReminder] = useState<Reminder | undefined>(undefined)
  const [refreshKey, setRefreshKey] = useState(0)

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
