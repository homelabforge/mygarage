import { useState } from 'react'
import WarrantyList from '../WarrantyList'
import WarrantyForm from '../WarrantyForm'
import type { WarrantyRecord } from '../../types/warranty'

interface WarrantiesTabProps {
  vin: string
}

export default function WarrantiesTab({ vin }: WarrantiesTabProps) {
  const [showForm, setShowForm] = useState(false)
  const [editRecord, setEditRecord] = useState<WarrantyRecord | undefined>()
  const [refreshKey, setRefreshKey] = useState(0)

  const handleAddClick = () => {
    setEditRecord(undefined)
    setShowForm(true)
  }

  const handleEditClick = (record: WarrantyRecord) => {
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
      <WarrantyList
        vin={vin}
        onAddClick={handleAddClick}
        onEditClick={handleEditClick}
        key={refreshKey}
      />

      {showForm && (
        <WarrantyForm
          vin={vin}
          record={editRecord}
          onClose={handleCloseForm}
          onSuccess={handleSuccess}
        />
      )}
    </>
  )
}
