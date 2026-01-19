import { useState, useEffect, useCallback } from 'react'
import { Download, Trash2, FileText, Image, AlertCircle } from 'lucide-react'
import { formatDateForDisplay } from '../utils/dateUtils'
import { toast } from 'sonner'
import api from '../services/api'
import type { Attachment } from '../types/attachment'

interface ServiceVisitAttachmentListProps {
  visitId: number
  refreshTrigger?: number
}

export default function ServiceVisitAttachmentList({
  visitId,
  refreshTrigger,
}: ServiceVisitAttachmentListProps) {
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
      setError(err instanceof Error ? err.message : 'An error occurred')
    }
  }, [visitId])

  useEffect(() => {
    setLoading(true)
    fetchAttachments().finally(() => setLoading(false))
  }, [fetchAttachments, refreshTrigger])

  const handleDelete = async (attachmentId: number) => {
    if (!confirm('Are you sure you want to delete this attachment?')) {
      return
    }

    setDeletingId(attachmentId)
    try {
      await api.delete(`/attachments/${attachmentId}`)
      await fetchAttachments()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete attachment')
    } finally {
      setDeletingId(null)
    }
  }

  const handleDownload = async (attachment: Attachment) => {
    try {
      const response = await api.get(attachment.download_url, {
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
      toast.error(err instanceof Error ? err.message : 'Failed to download attachment')
    }
  }

  const getFileIcon = (fileType?: string) => {
    if (!fileType) return <FileText className="w-4 h-4" />
    if (fileType.startsWith('image/')) return <Image className="w-4 h-4" />
    return <FileText className="w-4 h-4" />
  }

  const formatFileSize = (bytes?: number): string => {
    if (!bytes) return 'Unknown size'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  if (loading) {
    return <div className="text-center py-4 text-garage-text-muted text-sm">Loading attachments...</div>
  }

  if (error) {
    return (
      <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md">
        <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
        <p className="text-sm text-danger">{error}</p>
      </div>
    )
  }

  if (attachments.length === 0) {
    return (
      <div className="text-center py-4 text-garage-text-muted text-sm">
        <FileText className="w-8 h-8 mx-auto mb-2 opacity-50" />
        <p>No attachments</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
        {attachments.map((attachment) => (
          <div
            key={attachment.id}
            className="flex items-center justify-between p-3 bg-garage-bg border border-garage-border rounded-md hover:border-primary/50 transition-colors"
          >
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <div className="text-garage-text-muted">{getFileIcon(attachment.file_type)}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-garage-text truncate">{attachment.file_name}</p>
                <p className="text-xs text-garage-text-muted">
                  {formatFileSize(attachment.file_size)} •{' '}
                  {formatDateForDisplay(attachment.uploaded_at.split('T')[0])}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => handleDownload(attachment)}
                className="p-2 text-primary hover:bg-primary/10 rounded transition-colors"
                aria-label="Download"
                title="Download"
              >
                <Download className="w-4 h-4" />
              </button>
              <button
                onClick={() => handleDelete(attachment.id)}
                disabled={deletingId === attachment.id}
                className="p-2 text-danger hover:bg-danger/10 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                aria-label="Delete"
                title="Delete"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}
    </div>
  )
}
