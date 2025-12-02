import { useState } from 'react'
import PhotoGallery from '../PhotoGallery'
import PhotoUpload from '../PhotoUpload'

interface PhotosTabProps {
  vin: string
}

export default function PhotosTab({ vin }: PhotosTabProps) {
  const [showUpload, setShowUpload] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleAddClick = () => {
    setShowUpload(true)
  }

  const handleCloseUpload = () => {
    setShowUpload(false)
  }

  const handleSuccess = () => {
    setRefreshKey(k => k + 1)
    handleCloseUpload()
  }

  return (
    <>
      <PhotoGallery
        vin={vin}
        onAddClick={handleAddClick}
        key={refreshKey}
      />

      {showUpload && (
        <PhotoUpload
          vin={vin}
          onClose={handleCloseUpload}
          onSuccess={handleSuccess}
        />
      )}
    </>
  )
}
