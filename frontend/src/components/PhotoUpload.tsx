import { useState, useRef } from 'react'
import { Upload, X } from 'lucide-react'
import api from '../services/api'

interface PhotoUploadProps {
  vin: string
  onSuccess: () => void
  onClose: () => void
}

export default function PhotoUpload({ vin, onSuccess, onClose }: PhotoUploadProps) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [caption, setCaption] = useState('')
  const [setAsMain, setSetAsMain] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0])
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0])
    }
  }

  const handleFile = (selectedFile: File) => {
    // Validate file type
    const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic', 'image/heif']
    if (!validTypes.includes(selectedFile.type)) {
      setError('Please select a valid image file (JPG, PNG, or WEBP)')
      return
    }

    // Validate file size (10MB)
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError('File size must be less than 10MB')
      return
    }

    setFile(selectedFile)
    setError(null)

    // Create preview
    const reader = new FileReader()
    reader.onload = (e) => {
      setPreview(e.target?.result as string)
    }
    reader.readAsDataURL(selectedFile)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) return

    setUploading(true)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', file)
      if (caption) formData.append('caption', caption)
      formData.append('set_as_main', setAsMain.toString())

      await api.post(`/vehicles/${vin}/photos`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      onSuccess()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-garage-surface rounded-lg shadow-2xl max-w-2xl w-full border border-garage-border">
        <div className="bg-garage-surface border-b border-garage-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-garage-text">Upload Photo</h2>
          <button
            onClick={onClose}
            className="text-garage-text-muted hover:text-garage-text"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {!preview ? (
            <div
              className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
                dragActive
                  ? 'border-primary bg-primary/10'
                  : 'border-garage-border hover:border-primary/50'
              }`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
            >
              <Upload className="w-12 h-12 text-garage-text-muted mx-auto mb-4" />
              <p className="text-garage-text mb-2">
                Drag and drop an image here, or click to select
              </p>
              <p className="text-sm text-garage-text-muted mb-4">
                JPG, PNG, WEBP, or HEIC (max 10MB)
              </p>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/jpg,image/png,image/webp,image/heic,image/heif"
                onChange={handleFileInput}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="btn btn-primary rounded-lg transition-colors"
              >
                Select File
              </button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="relative">
                <img
                  src={preview}
                  alt="Preview"
                  className="w-full h-64 object-contain bg-garage-bg rounded-lg"
                />
                <button
                  type="button"
                  onClick={() => {
                    setPreview(null)
                    setFile(null)
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  className="absolute top-2 right-2 p-2 bg-danger text-white rounded-full hover:bg-danger/80"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              <div>
                <label htmlFor="caption" className="block text-sm font-medium text-garage-text mb-1">
                  Caption (optional)
                </label>
                <input
                  type="text"
                  id="caption"
                  maxLength={200}
                  value={caption}
                  onChange={(e) => setCaption(e.target.value)}
                  placeholder="Describe this photo..."
                  className="w-full px-3 py-2 border border-garage-border rounded-md focus:outline-none focus:ring-2 focus:ring-primary bg-garage-bg text-garage-text"
                />
              </div>

              <div className="flex items-center">
                <input
                  type="checkbox"
                  id="set_as_main"
                  checked={setAsMain}
                  onChange={(e) => setSetAsMain(e.target.checked)}
                  className="h-4 w-4 text-primary focus:ring-primary border-garage-border rounded bg-garage-bg"
                />
                <label htmlFor="set_as_main" className="ml-2 block text-sm text-garage-text">
                  Set as main vehicle photo
                </label>
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-4">
            <button
              type="submit"
              disabled={uploading || !file}
              className="flex items-center gap-2 btn btn-primary rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Upload className="w-4 h-4" />
              <span>{uploading ? 'Uploading...' : 'Upload Photo'}</span>
            </button>

            <button
              type="button"
              onClick={onClose}
              className="btn btn-primary rounded-lg transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
