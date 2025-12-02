import { useState } from 'react'
import FuelRecordList from '../FuelRecordList'
import FuelRecordForm from '../FuelRecordForm'
import type { FuelRecord } from '../../types/fuel'

interface FuelTabProps {
  vin: string
}

export default function FuelTab({ vin }: FuelTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editRecord, setEditRecord] = useState<FuelRecord | undefined>()
  const [refreshKey, setRefreshKey] = useState(0)

  const handleAddClick = () => {
    setEditRecord(undefined)
    setShowForm(true)
  }

  const handleEditClick = (record: FuelRecord) => {
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
      <FuelRecordList
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
        key={refreshKey}
      />

      {showForm && (
        <FuelRecordForm
          vin={vin}
          record={editRecord}
          onClose={handleCloseForm}
          onSuccess={handleSuccess}
        />
      )}
    </>
  )
}
