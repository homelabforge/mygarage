import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { formatAPITimestamp } from '../utils/parseAPITimestamp'
import { useDateLocale } from '../hooks/useDateLocale'
import { FileText, Plus, Trash2, Download, Edit3, Save, X } from 'lucide-react'
import { Button, IconButton, Card, Chip, Mono, EmptyState, Field, Input, Select, Textarea } from './ui'
import { toast } from 'sonner'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import type { Document } from '../types/document'
import { useDocuments, useDeleteDocument } from '../hooks/queries/useDocuments'
import { useQueryClient } from '@tanstack/react-query'

interface DocumentListProps {
  vin: string
  onAddClick: () => void
}

export default function DocumentList({ vin, onAddClick }: DocumentListProps) {
  const { t } = useTranslation('vehicles')
  const dateLocale = useDateLocale()
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editData, setEditData] = useState<{
    title: string
    document_type: string
    description: string
  }>({ title: '', document_type: '', description: '' })

  const { data, isLoading, error } = useDocuments(vin)
  const deleteMutation = useDeleteDocument(vin)
  const queryClient = useQueryClient()

  const documents = data?.documents ?? []

  const handleDelete = (documentId: number) => {
    if (!confirm(t('documentList.confirmDelete'))) {
      return
    }

    deleteMutation.mutate(documentId, {
      onError: (err) => {
        toast.error(getActionErrorMessage(err, t('documentList.deleteAction')))
      },
    })
  }

  const handleDownload = async (documentId: number, fileName: string) => {
    try {
      const response = await api.get(`/vehicles/${vin}/documents/${documentId}/download`, {
        responseType: 'blob',
      })

      const url = window.URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = fileName
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('documentList.downloadAction')))
    }
  }

  const [titleError, setTitleError] = useState<string | null>(null)

  const startEdit = (doc: Document) => {
    setTitleError(null)
    setEditingId(doc.id)
    setEditData({
      title: doc.title,
      document_type: doc.document_type || '',
      description: doc.description || '',
    })
  }

  const cancelEdit = () => {
    setEditingId(null)
    setEditData({ title: '', document_type: '', description: '' })
  }

  const saveEdit = async (documentId: number) => {
    // The API refuses a blank title too; catching it here keeps the edit open.
    if (!editData.title.trim()) {
      setTitleError(t('common:validation.document.titleRequired'))
      return
    }
    try {
      await api.put(`/vehicles/${vin}/documents/${documentId}`, editData)
      queryClient.invalidateQueries({ queryKey: ['documents', vin] })
      setEditingId(null)
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('documentList.updateAction')))
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes' // i18n-exempt - size unit
    const k = 1024
    // i18n-exempt - size units are not translatable
    const sizes = ['Bytes', 'KB', 'MB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  // uploaded_at is a datetime, not a calendar day: it takes the timestamp path.
  const formatDate = (value: string): string =>
    formatAPITimestamp(value, (d) => d.toLocaleDateString(dateLocale, { year: 'numeric', month: 'short', day: 'numeric' }))

  const getFileIcon = (mimeType: string) => {
    if (mimeType.startsWith('image/')) {
      return '\u{1F5BC}\u{FE0F}'
    } else if (mimeType === 'application/pdf') {
      return '\u{1F4C4}'
    } else if (mimeType.includes('word')) {
      return '\u{1F4DD}'
    } else if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) {
      return '\u{1F4CA}'
    }
    return '\u{1F4CE}'
  }

  if (isLoading) {
    return (
      <div className="flex justify-center items-center min-h-[200px]">
        <div className="text-text-mute">{t('documentList.loading')}</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-danger/10 border border-danger rounded-lg p-4">
        <p className="text-danger">{getActionErrorMessage(error, t('documentList.loadAction'))}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap justify-between items-center gap-3">
        <div className="flex items-center gap-2">
          <FileText aria-hidden="true" className="w-5 h-5 text-text-mute" />
          <h3 className="text-lg font-semibold text-text">{t('documentList.title')}</h3>
          <span className="text-sm text-text-mute">({t('documentList.fileCount', { count: documents.length })})</span>
        </div>
        <Button variant="primary" icon={Plus} onClick={onAddClick}>{t('documentList.uploadDocument')}</Button>
      </div>

      {documents.length === 0 ? (
        <EmptyState
          icon={FileText}
          title={t('documentList.noRecords')}
          description={t('documentList.noRecordsDesc')}
          action={
            <Button variant="primary" icon={Plus} onClick={onAddClick}>
              {t('documentList.uploadFirstDocument')}
            </Button>
          }
        />
      ) : (
        <div className="space-y-3">
          {documents.map((doc) => (
            <Card
              key={doc.id}
              padding="sm"
              className="hover:border-(--accent-line) transition-colors"
            >
              {editingId === doc.id ? (
                <div className="space-y-3">
                  <Field id="edit-title" label={t('documentList.titleLabel')} required error={titleError ?? undefined}>
                    <Input
                      id="edit-title"
                      type="text"
                      value={editData.title}
                      onChange={(e) => setEditData({ ...editData, title: e.target.value })}
                    />
                  </Field>
                  <Field id="edit-document_type" label={t('documentList.typeLabel')}>
                    <Select
                      id="edit-document_type"
                      value={editData.document_type}
                      onChange={(e) => setEditData({ ...editData, document_type: e.target.value })}
                      placeholder={t('documentList.selectType')}
                      options={[
                        { value: 'Insurance', label: t('documentList.typeInsurance') },
                        { value: 'Registration', label: t('documentList.typeRegistration') },
                        { value: 'Manual', label: t('documentList.typeManual') },
                        { value: 'Receipt', label: t('documentList.typeReceipt') },
                        { value: 'Inspection', label: t('documentList.typeInspection') },
                        { value: 'Other', label: t('documentList.typeOther') },
                      ]}
                    />
                  </Field>
                  <Field id="edit-description" label={t('documentList.descriptionLabel')}>
                    <Textarea
                      id="edit-description"
                      value={editData.description}
                      onChange={(e) => setEditData({ ...editData, description: e.target.value })}
                      rows={2}
                    />
                  </Field>
                  <div className="flex gap-2">
                    <Button variant="primary" size="sm" icon={Save} onClick={() => saveEdit(doc.id)}>
                      {t('documentList.save')}
                    </Button>
                    <Button variant="secondary" size="sm" icon={X} onClick={cancelEdit}>
                      {t('documentList.cancel')}
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-4">
                  <div aria-hidden="true" className="text-3xl flex-shrink-0">
                    {getFileIcon(doc.mime_type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <h4 className="text-text font-medium truncate">{doc.title}</h4>
                        <p className="text-sm text-text-mute truncate">{doc.file_name}</p>
                      </div>
                      {doc.document_type && (
                        <Chip className="flex-shrink-0">{doc.document_type}</Chip>
                      )}
                    </div>
                    {doc.description && (
                      <p className="text-sm text-text-mute mt-2">{doc.description}</p>
                    )}
                    <div className="flex items-center gap-4 mt-2 text-xs text-text-mute">
                      <Mono size="sm" tone="muted">{formatFileSize(doc.file_size)}</Mono>
                      <span>{t('documentList.uploaded')} <Mono size="sm" tone="muted">{formatDate(doc.uploaded_at)}</Mono></span>
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <IconButton icon={Download} label={t('documentList.download')} variant="ghost" size="sm" onClick={() => handleDownload(doc.id, doc.file_name)} />
                    <IconButton icon={Edit3} label={t('common:edit')} variant="ghost" size="sm" onClick={() => startEdit(doc)} />
                    <IconButton
                      icon={Trash2}
                      label={t('common:delete')}
                      variant="danger"
                      size="sm"
                      disabled={deleteMutation.isPending && deleteMutation.variables === doc.id}
                      onClick={() => handleDelete(doc.id)}
                    />
                  </div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
