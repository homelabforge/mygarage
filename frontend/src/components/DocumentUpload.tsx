import { useState, useRef, type SyntheticEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Upload, X, FileText } from 'lucide-react'
import { useUploadDocument } from '../hooks/queries/useDocuments'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { applyControlledFieldErrors } from '../hooks/useApiFormErrors'
import { usePublicSettings } from '../hooks/queries/usePublicSettings'
import { documentMaxBytes, megabytes } from '../utils/uploadLimits'
import { Button, IconButton, Mono, Field, Input, Select, Textarea } from './ui'

interface DocumentUploadProps {
  vin: string
  onSuccess: () => void
  onClose: () => void
}

export default function DocumentUpload({ vin, onSuccess, onClose }: DocumentUploadProps) {
  const { t } = useTranslation('vehicles')
  const uploadMutation = useUploadDocument(vin)
  const publicSettings = usePublicSettings()
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [documentType, setDocumentType] = useState<string>('')
  const [description, setDescription] = useState('')
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
    const ext = selectedFile.name.split('.').pop()?.toLowerCase()
    const validExtensions = ['pdf', 'doc', 'docx', 'txt', 'jpg', 'jpeg', 'png', 'webp', 'xls', 'xlsx', 'csv']

    if (!ext || !validExtensions.includes(ext)) {
      setError(t('documentUpload.misc.invalidFileType'))
      return
    }

    // The server's documents limit; unknown means the server checks alone.
    const maxBytes = documentMaxBytes(publicSettings)
    if (maxBytes !== null && selectedFile.size > maxBytes) {
      setError(t('documentUpload.misc.fileTooLargeLimit', { size: megabytes(maxBytes) }))
      return
    }

    setFile(selectedFile)
    setError(null)

    // Auto-populate title from filename if not set
    if (!title) {
      const fileName = selectedFile.name.replace(/\.[^/.]+$/, '') // Remove extension
      setTitle(fileName)
    }
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
      formData.append('title', title)
      if (documentType) formData.append('document_type', documentType)
      if (description) formData.append('description', description)

      await uploadMutation.mutateAsync(formData)

      onSuccess()
      onClose()
    } catch (err) {
      // Render targets: title, document_type, description. `file` has no
      // Field wrapper, so a problem addressed to it must hit the banner.
      const { attached, unhandled, errorsByField } = applyControlledFieldErrors(err, [
        'title',
        'document_type',
        'description',
      ])
      if (attached.length > 0) {
        setFieldErrors(errorsByField)
      }
      if (attached.length === 0 || unhandled.length > 0) {
        setError(getActionErrorMessage(err, t('documentUpload.uploadAction')))
      }
    } finally {
      setUploading(false)
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return t('documentUpload.misc.sizeZero')
    const k = 1024
    const sizes = [
      t('documentUpload.misc.unitBytes'),
      t('documentUpload.misc.unitKb'),
      t('documentUpload.misc.unitMb'),
    ]
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  return (
    <div className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50">
      <div className="bg-surface rounded-lg shadow-2xl max-w-2xl w-full border border-border">
        <div className="bg-surface border-b border-border px-6 py-4 flex justify-between items-center rounded-t-lg">
          <h2 className="text-xl font-semibold text-text">{t('documentUpload.title')}</h2>
          <IconButton icon={X} label={t('common:close')} variant="ghost" onClick={onClose} />
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-danger/10 border border-danger rounded-lg p-3">
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {!file ? (
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
                {t('documentUpload.misc.dragDropPrompt')}
              </p>
              <p className="text-sm text-text-mute mb-4">
                {t('documentUpload.misc.fileTypes')}
              </p>
              <label htmlFor="document-upload-file" className="sr-only">
                {t('documentUpload.misc.selectFile')}
              </label>
              <input
                id="document-upload-file"
                ref={fileInputRef}
                type="file"
                accept=".pdf,.doc,.docx,.txt,.jpg,.jpeg,.png,.webp,.xls,.xlsx,.csv"
                onChange={handleFileInput}
                className="hidden"
              />
              <Button type="button" variant="secondary" onClick={() => fileInputRef.current?.click()}>
                {t('documentUpload.misc.selectFile')}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="bg-surface-2 border border-border rounded-lg p-4">
                <div className="flex items-start gap-3">
                  <FileText aria-hidden="true" className="w-8 h-8 text-(--accent-fg) flex-shrink-0 mt-1" />
                  <div className="flex-1 min-w-0">
                    <p className="text-text font-medium truncate">{file.name}</p>
                    <Mono size="sm" tone="muted">{formatFileSize(file.size)}</Mono>
                  </div>
                  <IconButton
                    icon={X}
                    label={t('common:remove')}
                    variant="danger"
                    onClick={() => {
                      setFile(null)
                      if (fileInputRef.current) fileInputRef.current.value = ''
                    }}
                  />
                </div>
              </div>

              <Field id="title" label={t('documentList.titleLabel')} required error={fieldErrors.title}>
                <Input
                  id="title"
                  type="text"
                  required
                  maxLength={200}
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder={t('documentUpload.misc.titlePlaceholder')}
                />
              </Field>

              <Field id="document_type" label={t('documentUpload.misc.documentTypeLabel')} error={fieldErrors.document_type}>
                <Select
                  id="document_type"
                  value={documentType}
                  onChange={(e) => setDocumentType(e.target.value)}
                  placeholder={t('documentList.selectType')}
                  options={[
                    { value: 'Insurance', label: t('documentUpload.misc.typeInsurance') },
                    { value: 'Registration', label: t('documentUpload.misc.typeRegistration') },
                    { value: 'Manual', label: t('documentUpload.misc.typeManual') },
                    { value: 'Receipt', label: t('documentUpload.misc.typeReceipt') },
                    { value: 'Inspection', label: t('documentUpload.misc.typeInspection') },
                    { value: 'Other', label: t('documentUpload.misc.typeOther') },
                  ]}
                />
              </Field>

              <Field id="description" label={t('documentList.descriptionLabel')} error={fieldErrors.description}>
                <Textarea
                  id="description"
                  rows={3}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('documentUpload.misc.descriptionPlaceholder')}
                />
              </Field>
            </div>
          )}

          <div className="flex gap-3 pt-4">
            <Button type="submit" variant="primary" icon={Upload} loading={uploading} disabled={uploading || !file || !title}>
              {uploading ? t('documentUpload.uploading') : t('documentUpload.uploadBtn')}
            </Button>
            <Button type="button" variant="secondary" onClick={onClose}>
              {t('common:cancel')}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
