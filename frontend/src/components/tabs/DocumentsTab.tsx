import { useState } from 'react'
import DocumentList from '../DocumentList'
import DocumentUpload from '../DocumentUpload'

interface DocumentsTabProps {
  vin: string
}

export default function DocumentsTab({ vin }: DocumentsTabProps) {
  const [showUpload, setShowUpload] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  const handleUploadSuccess = () => {
    setRefreshKey(prev => prev + 1)
  }

  return (
    <>
      <DocumentList
        key={refreshKey}
        vin={vin}
        onAddClick={() => setShowUpload(true)}
      />

      {showUpload && (
        <DocumentUpload
          vin={vin}
          onSuccess={handleUploadSuccess}
          onClose={() => setShowUpload(false)}
        />
      )}
    </>
  )
}
