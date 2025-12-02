import { useState } from 'react'
import OdometerRecordList from '../OdometerRecordList'
import OdometerRecordForm from '../OdometerRecordForm'
import type { OdometerRecord } from '../../types/odometer'

interface OdometerTabProps {
  vin: string
}

export default function OdometerTab({ vin }: OdometerTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editRecord, setEditRecord] = useState<OdometerRecord | undefined>()
  const [refreshKey, setRefreshKey] = useState(0)

  const handleAddClick = () => {
    setEditRecord(undefined)
    setShowForm(true)
  }

  const handleEditClick = (record: OdometerRecord) => {
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
      <OdometerRecordList
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
        key={refreshKey}
      />

      {showForm && (
        <OdometerRecordForm
          vin={vin}
          record={editRecord}
          onClose={handleCloseForm}
          onSuccess={handleSuccess}
        />
      )}
    </>
  )
}
