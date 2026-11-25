import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Trash2, FileText, Image, AlertCircle } from 'lucide-react'
import { formatAPITimestamp } from '../utils/parseAPITimestamp'
import { useDateLocale } from '../hooks/useDateLocale'
import { toast } from 'sonner'
import api from '../services/api'
import { getActionErrorMessage } from '../utils/httpErrorHandler'
import { apiRelative } from '../utils/basePath'
import type { Attachment } from '../types/attachment'
import { Card, IconButton, EmptyState, Mono, useConfirm } from './ui'

interface ServiceVisitAttachmentListProps {
  visitId: number
  refreshTrigger?: number
}

export default function ServiceVisitAttachmentList({
  visitId,
  refreshTrigger,
}: ServiceVisitAttachmentListProps) {
  const { t } = useTranslation('vehicles')
  const confirm = useConfirm()
  const dateLocale = useDateLocale()
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const fetchAttachments = useCallback(async () => {
    try {
      const response = await api.get(`/service-visits/${visitId}/attachments`)
      setAttachments(response.data.attachments)
      setError(null)
    } catch (err) {
      setError(getActionErrorMessage(err, t('serviceVisitAttachments.loadAction')))
    }
  }, [visitId, t])

  useEffect(() => {
    setLoading(true)
    fetchAttachments().finally(() => setLoading(false))
  }, [fetchAttachments, refreshTrigger])

  const handleDelete = async (attachmentId: number): Promise<void> => {
    if (!(await confirm({ message: t('serviceVisitAttachments.confirmDelete'), confirmLabel: t('common:delete') }))) {
      return
    }

    setDeletingId(attachmentId)
    try {
      await api.delete(`/attachments/${attachmentId}`)
      await fetchAttachments()
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('serviceVisitAttachments.deleteAction')))
    } finally {
      setDeletingId(null)
    }
  }

  const handleDownload = async (attachment: Attachment) => {
    try {
      const response = await api.get(apiRelative(attachment.download_url), {
        responseType: 'blob',
      })

      const url = window.URL.createObjectURL(response.data)
      const a = document.createElement('a')
      a.href = url
      a.download = attachment.file_name
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      toast.error(getActionErrorMessage(err, t('serviceVisitAttachments.downloadAction')))
    }
  }

  const getFileIcon = (fileType?: string | null) => {
    if (!fileType) return <FileText aria-hidden="true" className="w-4 h-4" />
    if (fileType.startsWith('image/')) return <Image aria-hidden="true" className="w-4 h-4" />
    return <FileText aria-hidden="true" className="w-4 h-4" />
  }

  const formatFileSize = (bytes?: number | null): string => {
    if (!bytes) return t('serviceVisitAttachments.unknownSize')
    if (bytes < 1024) return t('serviceVisitAttachments.sizeBytes', { size: bytes })
    if (bytes < 1024 * 1024) return t('serviceVisitAttachments.sizeKb', { size: (bytes / 1024).toFixed(1) })
    return t('serviceVisitAttachments.sizeMb', { size: (bytes / 1024 / 1024).toFixed(1) })
  }

  if (loading) {
    return <div className="text-center py-4 text-text-mute text-sm">{t('serviceVisitAttachments.loading')}</div>
  }

  if (error) {
    return (
      <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md">
        <AlertCircle aria-hidden="true" className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
        <p className="text-sm text-danger">{error}</p>
      </div>
    )
  }

  if (attachments.length === 0) {
    return <EmptyState size="sm" icon={FileText} title={t('serviceVisitAttachments.empty')} />
  }

  return (
    <div className="space-y-2">
      {attachments.map((attachment) => (
        <Card key={attachment.id} padding="sm">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <div className="text-text-mute">{getFileIcon(attachment.file_type)}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-text truncate">{attachment.file_name}</p>
                <Mono as="p" size="xs" tone="muted">
                  {formatFileSize(attachment.file_size)} • {formatAPITimestamp(attachment.uploaded_at, (d) => d.toLocaleDateString(dateLocale, { year: 'numeric', month: 'short', day: 'numeric' }))}
                </Mono>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <IconButton
                icon={Download}
                label={t('serviceVisitAttachments.download')}
                variant="ghost"
                size="sm"
                onClick={() => handleDownload(attachment)}
              />
              <IconButton
                icon={Trash2}
                label={t('common:delete')}
                variant="danger"
                size="sm"
                disabled={deletingId === attachment.id}
                onClick={() => void handleDelete(attachment.id)}
              />
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}
