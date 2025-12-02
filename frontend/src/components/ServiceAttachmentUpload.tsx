import { useState, useRef } from 'react'
import { Upload, X, AlertCircle } from 'lucide-react'
import api from '../services/api'

interface ServiceAttachmentUploadProps {
  recordId: number
  onUploadSuccess: () => void
}

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10MB
const ALLOWED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'application/pdf']
const ALLOWED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.pdf']

export default function ServiceAttachmentUpload({ recordId, onUploadSuccess }: ServiceAttachmentUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const validateFile = (file: File): string | null => {
    // Check file size
    if (file.size > MAX_FILE_SIZE) {
      return `File size exceeds 10MB limit (${(file.size / 1024 / 1024).toFixed(2)}MB)`
    }

    // Check file type
    const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase()
    if (!ALLOWED_TYPES.includes(file.type) && !ALLOWED_EXTENSIONS.includes(fileExtension)) {
      return `File type not allowed. Supported: JPG, PNG, GIF, PDF`
    }

    return null
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const validationError = validateFile(file)
    if (validationError) {
      setError(validationError)
      setSelectedFile(null)
      return
    }

    setError(null)
    setSelectedFile(file)
  }

  const handleUpload = async () => {
    if (!selectedFile) return

    setUploading(true)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)

      await api.post(`/service/${recordId}/attachments`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      // Reset state
      setSelectedFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }

      // Notify parent
      onUploadSuccess()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to upload file')
    } finally {
      setUploading(false)
    }
  }

  const handleCancel = () => {
    setSelectedFile(null)
    setError(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-sm font-medium text-garage-text mb-2">
          Upload Attachment
        </label>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.gif,.pdf"
            onChange={handleFileSelect}
            className="hidden"
            id="file-upload"
          />
          <label
            htmlFor="file-upload"
            className="flex-1 px-4 py-2 border border-garage-border rounded-md bg-garage-bg text-garage-text cursor-pointer hover:border-primary transition-colors flex items-center gap-2"
          >
            <Upload className="w-4 h-4" />
            <span className="text-sm">
              {selectedFile ? selectedFile.name : 'Choose file (JPG, PNG, GIF, PDF - Max 10MB)'}
            </span>
          </label>
          {selectedFile && (
            <>
              <button
                onClick={handleUpload}
                disabled={uploading}
                className="px-4 py-2 bg-primary text-white rounded-md hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {uploading ? 'Uploading...' : 'Upload'}
              </button>
              <button
                onClick={handleCancel}
                disabled={uploading}
                className="p-2 text-garage-text-muted hover:text-danger transition-colors"
                aria-label="Cancel"
              >
                <X className="w-5 h-5" />
              </button>
            </>
          )}
        </div>
        <p className="mt-1 text-xs text-garage-text-muted">
          Supported formats: JPG, PNG, GIF, PDF (max 10MB)
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md">
          <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
          <p className="text-sm text-danger">{error}</p>
        </div>
      )}
    </div>
  )
}
