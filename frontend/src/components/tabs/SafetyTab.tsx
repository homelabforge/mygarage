import { useState } from 'react'
import RecallList from '../RecallList'
import RecallForm from '../RecallForm'
import type { Recall } from '../../types/recall'

interface SafetyTabProps {
  vin: string
}

export default function SafetyTab({ vin }: SafetyTabProps) {
  const [showRecallForm, setShowRecallForm] = useState(false)
  const [editingRecall, setEditingRecall] = useState<Recall | undefined>(undefined)

  const handleAddRecall = () => {
    setEditingRecall(undefined)
    setShowRecallForm(true)
  }

  const handleEditRecall = (recall: Recall) => {
    setEditingRecall(recall)
    setShowRecallForm(true)
  }

  const handleCloseRecallForm = () => {
    setShowRecallForm(false)
    setEditingRecall(undefined)
  }

  const handleRecallSuccess = () => {
    window.dispatchEvent(new Event('recalls-refresh'))
  }

  return (
    <div>
      <RecallList
        vin={vin}
        onAddClick={handleAddRecall}
        onEditClick={handleEditRecall}
        onRefresh={handleRecallSuccess}
      />

      {showRecallForm && (
        <RecallForm
          vin={vin}
          recall={editingRecall}
          onClose={handleCloseRecallForm}
          onSuccess={handleRecallSuccess}
        />
      )}
    </div>
  )
}
