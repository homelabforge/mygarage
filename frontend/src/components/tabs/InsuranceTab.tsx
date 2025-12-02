import { useState } from 'react'
import InsuranceList from '../InsuranceList'
import InsuranceForm from '../InsuranceForm'
import type { InsurancePolicy } from '../../types/insurance'

interface InsuranceTabProps {
  vin: string
}

export default function InsuranceTab({ vin }: InsuranceTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editRecord, setEditRecord] = useState<InsurancePolicy | undefined>()
  const [refreshKey, setRefreshKey] = useState(0)

  const handleAddClick = () => {
    setEditRecord(undefined)
    setShowForm(true)
  }

  const handleEditClick = (record: InsurancePolicy) => {
    setEditRecord(record)
    setShowForm(true)
  }

  const handleCloseForm = () => {
    setShowForm(false)
    setEditRecord(undefined)
  }

  const handleSuccess = () => {
    setRefreshKey(k => k + 1)
    handleCloseForm()
  }

  return (
    <>
      <InsuranceList
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
        key={refreshKey}
      />

      {showForm && (
        <InsuranceForm
          vin={vin}
          record={editRecord}
          onClose={handleCloseForm}
          onSuccess={handleSuccess}
        />
      )}
    </>
  )
}
