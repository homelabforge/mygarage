import { useState, useRef, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, X } from 'lucide-react'
import api from '../services/api'
import { actionErrorMessage } from '../utils/httpErrorHandler'
import { applyControlledFieldErrors } from '../utils/apiFormErrors'
import { Button, IconButton, Field, Input, Checkbox } from './ui'

interface PhotoUploadProps {
  vin: string
  onSuccess: () => void
  onClose: () => void
}

export default function PhotoUpload({ vin, onSuccess, onClose }: PhotoUploadProps) {
  const { t } = useTranslation('vehicles')
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
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
      setError(t('photoUpload.errorInvalidType'))
      return
    }

    // Validate file size (10MB)
    if (selectedFile.size > 10 * 1024 * 1024) {
      setError(t('photoUpload.errorTooLarge'))
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

  const handleSubmit = async (e: SyntheticEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!file) return

    setUploading(true)
    setError(null)
    setFieldErrors({})

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
      // Render targets: caption only. `set_as_main` has no Field wrapper, so
      // a problem addressed to it must hit the banner instead of vanishing.
      const { parsed, attached, unhandled, errorsByField } = applyControlledFieldErrors(err, ['caption'])
      if (attached.length > 0) {
        setFieldErrors(errorsByField)
      }
      if (attached.length === 0 || unhandled.length > 0) {
        setError(actionErrorMessage(parsed, t('photoUpload.uploadAction')))
      }
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-surface rounded-lg shadow-2xl max-w-2xl w-full border border-border">
        <div className="bg-surface border-b border-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-text">{t('photoUpload.title')}</h2>
          <IconButton icon={X} label={t('common:close')} variant="ghost" onClick={onClose} />
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
                  ? 'border-(--accent-line) bg-(--accent-soft)'
                  : 'border-border hover:border-(--accent-line)'
              }`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
            >
              <Upload aria-hidden="true" className="w-12 h-12 text-text-mute mx-auto mb-4" />
              <p className="text-text mb-2">
                {t('photoUpload.dragDrop')}
              </p>
              <p className="text-sm text-text-mute mb-4">
                {t('photoUpload.fileTypesHint')}
              </p>
              <label htmlFor="photo-upload-file" className="sr-only">
                {t('photoUpload.selectFile')}
              </label>
              <input
                id="photo-upload-file"
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/jpg,image/png,image/webp,image/heic,image/heif"
                onChange={handleFileInput}
                className="hidden"
              />
              <Button type="button" variant="secondary" onClick={() => fileInputRef.current?.click()}>
                {t('photoUpload.selectFile')}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="relative">
                <img
                  src={preview}
                  alt={t('photoUpload.previewAlt')}
                  className="w-full h-64 object-contain bg-surface-2 rounded-lg"
                />
                <IconButton
                  icon={X}
                  label={t('common:remove')}
                  variant="danger"
                  className="absolute top-2 right-2"
                  onClick={() => {
                    setPreview(null)
                    setFile(null)
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                />
              </div>

              <Field id="caption" label={t('photoUpload.captionLabel')} error={fieldErrors.caption}>
                <Input
                  id="caption"
                  type="text"
                  maxLength={200}
                  value={caption}
                  onChange={(e) => setCaption(e.target.value)}
                  placeholder={t('photoUpload.captionPlaceholder')}
                />
              </Field>

              <Checkbox
                id="set_as_main"
                label={t('photoUpload.setAsMain')}
                checked={setAsMain}
                onChange={(e) => setSetAsMain(e.target.checked)}
              />
            </div>
          )}

          <div className="flex gap-3 pt-4">
            <Button type="submit" variant="primary" icon={Upload} loading={uploading} disabled={uploading || !file}>
              {uploading ? t('photoUpload.uploading') : t('photoUpload.uploadBtn')}
            </Button>
            <Button type="button" variant="secondary" onClick={onClose}>
              {t('photoUpload.cancel')}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
