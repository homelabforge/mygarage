import { useState } from 'react'
import RecallList from '../RecallList'
import RecallForm from '../RecallForm'
import type { Recall } from '../../types/recall'

interface RecallsTabProps {
  vin: string
}

export default function RecallsTab({ vin }: RecallsTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editingRecall, setEditingRecall] = useState<Recall | undefined>(undefined)

  const handleAddClick = () => {
    setEditingRecall(undefined)
    setShowForm(true)
  }

  const handleEditClick = (recall: Recall) => {
    setEditingRecall(recall)
    setShowForm(true)
  }

  const handleCloseForm = () => {
    setShowForm(false)
    setEditingRecall(undefined)
  }

  const handleSuccess = () => {
    window.dispatchEvent(new Event('recalls-refresh'))
  }

  return (
    <div>
      <RecallList
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
        onRefresh={handleSuccess}
      />

      {showForm && (
        <RecallForm
          vin={vin}
          recall={editingRecall}
          onClose={handleCloseForm}
          onSuccess={handleSuccess}
        />
      )}
    </div>
  )
}
