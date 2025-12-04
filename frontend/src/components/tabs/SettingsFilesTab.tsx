import { useState, useEffect, useCallback } from 'react'
import { HardDrive, FileText } from 'lucide-react'
import { useSettings } from '@/contexts/SettingsContext'
import api from '@/services/api'

type SettingRecord = {
  key: string
  value: string | null
}

type SettingsResponse = {
  settings: SettingRecord[]
}

export default function SettingsFilesTab() {
  const [loading, setLoading] = useState(true)
  const { triggerSave, registerSaveHandler, unregisterSaveHandler } = useSettings()
  const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null)

  const [formData, setFormData] = useState({
    max_upload_size_mb: '10',
    allowed_photo_types: ['jpg', 'jpeg', 'png', 'webp'],
    allowed_attachment_types: ['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'],
    window_sticker_enabled: 'true',
    window_sticker_ocr_enabled: 'true',
  })
  const [loadedFormData, setLoadedFormData] = useState<typeof formData | null>(null)

  const loadSettings = useCallback(async () => {
    try {
      const response = await api.get('/settings')
      const data: SettingsResponse = response.data

      const settingsMap: Record<string, string> = {}
      data.settings.forEach((setting) => {
        settingsMap[setting.key] = setting.value || ''
      })

      const newFormData = {
        max_upload_size_mb: settingsMap['max_upload_size_mb'] || '10',
        allowed_photo_types: settingsMap['allowed_photo_types']
          ? settingsMap['allowed_photo_types'].split(',')
          : ['jpg', 'jpeg', 'png', 'webp'],
        allowed_attachment_types: settingsMap['allowed_attachment_types']
          ? settingsMap['allowed_attachment_types'].split(',')
          : ['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx'],
        window_sticker_enabled: settingsMap['window_sticker_enabled'] || 'true',
        window_sticker_ocr_enabled: settingsMap['window_sticker_ocr_enabled'] || 'true',
      }
      setFormData(newFormData)
      setLoadedFormData(newFormData)
    } catch {
      // Removed console.error
      setMessage({ type: 'error', text: 'Failed to load settings' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSettings()
  }, [loadSettings])

  const handleSave = useCallback(async () => {
    await api.post('/settings/batch', {
      settings: {
        max_upload_size_mb: formData.max_upload_size_mb,
        allowed_photo_types: formData.allowed_photo_types.join(','),
        allowed_attachment_types: formData.allowed_attachment_types.join(','),
        window_sticker_enabled: formData.window_sticker_enabled,
        window_sticker_ocr_enabled: formData.window_sticker_ocr_enabled,
      },
    })
  }, [formData])

  // Register save handler
  useEffect(() => {
    registerSaveHandler('files', handleSave)
    return () => unregisterSaveHandler('files')
  }, [handleSave, registerSaveHandler, unregisterSaveHandler])

  // Auto-save when form data changes (after initial load)
  useEffect(() => {
    if (!loadedFormData) return // Nothing loaded yet

    if (JSON.stringify(formData) !== JSON.stringify(loadedFormData)) {
      triggerSave()
    }
  }, [formData, loadedFormData, triggerSave])

  const togglePhotoType = (type: string) => {
    if (formData.allowed_photo_types.includes(type)) {
      setFormData({
        ...formData,
        allowed_photo_types: formData.allowed_photo_types.filter((t) => t !== type),
      })
    } else {
      setFormData({
        ...formData,
        allowed_photo_types: [...formData.allowed_photo_types, type],
      })
    }
  }

  const toggleAttachmentType = (type: string) => {
    if (formData.allowed_attachment_types.includes(type)) {
      setFormData({
        ...formData,
        allowed_attachment_types: formData.allowed_attachment_types.filter((t) => t !== type),
      })
    } else {
      setFormData({
        ...formData,
        allowed_attachment_types: [...formData.allowed_attachment_types, type],
      })
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-garage-text-muted">Loading settings...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Success/Error Messages */}
      {message && (
        <div
          className={`p-4 rounded-lg border ${
            message.type === 'success'
              ? 'bg-success-500/10 border-success-500 text-success-500'
              : 'bg-danger-500/10 border-danger-500 text-danger-500'
          }`}
        >
          {message.text}
        </div>
      )}

      {/* File Management Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* File Management Settings */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <HardDrive className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">File Management Settings</h2>
              <p className="text-sm text-garage-text-muted">
                Configure file upload limits and allowed file types
              </p>
            </div>
          </div>

          <div className="space-y-6">
          {/* Max Upload Size */}
          <div>
            <label htmlFor="max_upload_size" className="block text-sm font-medium text-garage-text mb-2">
              Maximum Upload Size (MB)
            </label>
            <input
              type="number"
              id="max_upload_size"
              value={formData.max_upload_size_mb}
              onChange={(e) => setFormData({ ...formData, max_upload_size_mb: e.target.value })}
              min="1"
              max="100"
              className="w-full px-3 py-2 bg-garage-bg border border-garage-border rounded-lg text-garage-text focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <p className="mt-1 text-sm text-garage-text-muted">
              Maximum file size per upload (1-100 MB)
            </p>
          </div>

          {/* Allowed Photo Types */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              Allowed Photo Types
            </label>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].map((type) => (
                <label
                  key={type}
                  className="flex items-center p-3 bg-garage-bg border border-garage-border rounded-lg cursor-pointer hover:border-primary transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={formData.allowed_photo_types.includes(type)}
                    onChange={() => togglePhotoType(type)}
                    className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                  />
                  <span className="ml-2 text-sm text-garage-text font-mono">.{type}</span>
                </label>
              ))}
            </div>
            <p className="mt-1 text-sm text-garage-text-muted">
              File types allowed for vehicle photos
            </p>
          </div>

          {/* Allowed Attachment Types */}
          <div>
            <label className="block text-sm font-medium text-garage-text mb-2">
              Allowed Attachment Types
            </label>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {['pdf', 'jpg', 'jpeg', 'png', 'doc', 'docx', 'xls', 'xlsx', 'txt'].map((type) => (
                <label
                  key={type}
                  className="flex items-center p-3 bg-garage-bg border border-garage-border rounded-lg cursor-pointer hover:border-primary transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={formData.allowed_attachment_types.includes(type)}
                    onChange={() => toggleAttachmentType(type)}
                    className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                  />
                  <span className="ml-2 text-sm text-garage-text font-mono">.{type}</span>
                </label>
              ))}
            </div>
            <p className="mt-1 text-sm text-garage-text-muted">
              File types allowed for documents and attachments
            </p>
          </div>

          {/* Storage Info */}
          <div className="pt-6 border-t border-garage-border">
            <h3 className="text-lg font-medium text-garage-text mb-4">Storage Information</h3>
            <div className="bg-garage-bg rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-3">
                <HardDrive className="w-5 h-5 text-primary" />
                <div className="flex-1">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-garage-text-muted">Data Directory:</span>
                    <span className="text-sm text-garage-text font-mono">/app/data</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <HardDrive className="w-5 h-5 text-primary" />
                <div className="flex-1">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-garage-text-muted">Photos Directory:</span>
                    <span className="text-sm text-garage-text font-mono">/app/data/photos</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <HardDrive className="w-5 h-5 text-primary" />
                <div className="flex-1">
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-garage-text-muted">Documents Directory:</span>
                    <span className="text-sm text-garage-text font-mono">/app/data/documents</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          </div>
        </div>

        {/* Window Sticker */}
        <div className="bg-garage-surface rounded-lg border border-garage-border p-6">
          <div className="flex items-start gap-3 mb-6">
            <FileText className="w-6 h-6 text-primary mt-1" />
            <div className="flex-1">
              <h2 className="text-xl font-semibold text-garage-text mb-2">Window Sticker</h2>
              <p className="text-sm text-garage-text-muted">
                Upload window stickers (Monroney labels) and automatically extract vehicle specifications and pricing data
              </p>
            </div>
          </div>

          <div className="space-y-6">
            {/* Enable Window Sticker */}
            <div>
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={formData.window_sticker_enabled === 'true'}
                  onChange={(e) => setFormData({ ...formData, window_sticker_enabled: e.target.checked ? 'true' : 'false' })}
                  className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2"
                />
                <span className="ml-2 text-sm text-garage-text font-medium">
                  Enable window sticker upload
                </span>
              </label>
              <p className="mt-1 ml-6 text-sm text-garage-text-muted">
                Allow uploading window sticker PDFs and images for your vehicles
              </p>
            </div>

            {/* Enable OCR */}
            <div>
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={formData.window_sticker_ocr_enabled === 'true'}
                  disabled={formData.window_sticker_enabled === 'false'}
                  onChange={(e) => setFormData({ ...formData, window_sticker_ocr_enabled: e.target.checked ? 'true' : 'false' })}
                  className="w-4 h-4 text-primary bg-garage-bg border-garage-border rounded focus:ring-primary focus:ring-2 disabled:opacity-50"
                />
                <span className="ml-2 text-sm text-garage-text font-medium">
                  Enable automatic data extraction (OCR)
                </span>
              </label>
              <p className="mt-1 ml-6 text-sm text-garage-text-muted">
                Automatically extract MSRP, fuel economy, and equipment data from uploaded stickers
              </p>
            </div>

            <div className="bg-garage-bg rounded-lg p-4 border border-garage-border">
              <h3 className="text-sm font-medium text-garage-text mb-2">About Window Stickers</h3>
              <p className="text-sm text-garage-text-muted">
                Window stickers (Monroney labels) are federally mandated labels on new vehicles showing MSRP, fuel economy, standard equipment, and optional features.
                Upload your vehicle's window sticker to automatically populate pricing and specification data.
              </p>
              <p className="text-sm text-garage-text-muted mt-2">
                <strong>Supported formats:</strong> PDF, JPG, PNG (up to 10MB)
              </p>
              <p className="text-sm text-garage-text-muted mt-2">
                <strong>Note:</strong> Window stickers are only available for passenger cars and trucks, not RVs, trailers, or fifth wheels.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
