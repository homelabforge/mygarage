import { useState, useEffect, useRef, useCallback } from 'react'
import { X, Download, Eye, FileText, Image as ImageIcon, AlertCircle } from 'lucide-react'
import { formatDateForDisplay } from '../utils/dateUtils'
import { toast } from 'sonner'
import api from '../services/api'
import type { Attachment } from '../types/attachment'
import AttachmentPreview from './AttachmentPreview'

interface AttachmentQuickViewProps {
  recordId: number
  onClose: () => void
  position: { top: number; left: number }
}

export default function AttachmentQuickView({ recordId, onClose, position }: AttachmentQuickViewProps) {
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [previewAttachment, setPreviewAttachment] = useState<Attachment | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)

  const fetchAttachments = useCallback(async () => {
    try {
      setLoading(true)
      const response = await api.get(`/service/${recordId}/attachments`)
      setAttachments(response.data.attachments)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setLoading(false)
    }
  }, [recordId])

  useEffect(() => {
    fetchAttachments()
  }, [fetchAttachments])

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (cardRef.current && !cardRef.current.contains(event.target as Node)) {
        onClose()
      }
    }

    // Close on ESC key
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [onClose])

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
    if (fileType.startsWith('image/')) return <ImageIcon className="w-4 h-4" />
    return <FileText className="w-4 h-4" />
  }

  const formatFileSize = (bytes?: number): string => {
    if (!bytes) return 'Unknown size'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const canPreview = (fileType?: string): boolean => {
    if (!fileType) return false
    return fileType.startsWith('image/') || fileType === 'application/pdf'
  }

  return (
    <>
      {previewAttachment && (
        <AttachmentPreview
          attachment={previewAttachment}
          onClose={() => setPreviewAttachment(null)}
        />
      )}

      <div
        ref={cardRef}
        className="fixed bg-garage-surface border-2 border-primary rounded-lg shadow-2xl max-w-md w-full z-40"
        style={{
          top: `${position.top}px`,
          left: `${position.left}px`,
          maxHeight: '400px',
        }}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-garage-border">
          <h3 className="text-lg font-semibold text-garage-text">Attachments</h3>
          <button
            onClick={onClose}
            className="p-1 text-garage-text-muted hover:text-garage-text transition-colors"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 overflow-y-auto" style={{ maxHeight: '320px' }}>
          {loading && (
            <div className="text-center py-8 text-garage-text-muted">
              Loading attachments...
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 p-3 bg-danger/10 border border-danger/20 rounded-md">
              <AlertCircle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
              <p className="text-sm text-danger">{error}</p>
            </div>
          )}

          {!loading && !error && attachments.length === 0 && (
            <div className="text-center py-8 text-garage-text-muted">
              <FileText className="w-12 h-12 mx-auto mb-2 opacity-50" />
              <p>No attachments</p>
            </div>
          )}

          {!loading && !error && attachments.length > 0 && (
            <div className="space-y-2">
              {attachments.map((attachment) => (
                <div
                  key={attachment.id}
                  className="flex items-center justify-between p-3 bg-garage-bg border border-garage-border rounded-md hover:border-primary/50 transition-colors"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <div className="text-garage-text-muted">
                      {getFileIcon(attachment.file_type)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-garage-text truncate">
                        {attachment.file_name}
                      </p>
                      <p className="text-xs text-garage-text-muted">
                        {formatFileSize(attachment.file_size)} • {formatDateForDisplay(attachment.uploaded_at.split('T')[0])}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    {canPreview(attachment.file_type) && (
                      <button
                        onClick={() => setPreviewAttachment(attachment)}
                        className="p-2 text-primary hover:bg-primary/10 rounded transition-colors"
                        aria-label="Preview"
                        title="Preview"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                    )}
                    <button
                      onClick={() => handleDownload(attachment)}
                      className="p-2 text-primary hover:bg-primary/10 rounded transition-colors"
                      aria-label="Download"
                      title="Download"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
