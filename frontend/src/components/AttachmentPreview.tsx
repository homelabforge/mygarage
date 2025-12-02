import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import type { Attachment } from '../types/attachment'

interface AttachmentPreviewProps {
  attachment: Attachment
  onClose: () => void
}

export default function AttachmentPreview({ attachment, onClose }: AttachmentPreviewProps) {
  const isImage = attachment.file_type?.startsWith('image/')
  const isPDF = attachment.file_type === 'application/pdf'

  // Handle ESC key to close
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose()
    }
  }

  const handleContentClick = (e: React.MouseEvent) => {
    e.stopPropagation()
  }

  const modalContent = (
    <div
      className="fixed inset-0 modal-overlay flex items-center justify-center p-4 z-50"
      onClick={handleBackdropClick}
    >
      <div className="relative max-w-7xl w-full h-full flex flex-col" onClick={handleContentClick}>
        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-white truncate">
            {attachment.file_name}
          </h2>
          <button
            onClick={onClose}
            className="p-2 text-white hover:bg-white/10 rounded-lg transition-colors"
            aria-label="Close preview"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 flex items-center justify-center overflow-auto">
          {isImage && (
            <img
              src={attachment.view_url || attachment.download_url}
              alt={attachment.file_name}
              className="max-w-full max-h-full object-contain rounded-lg"
            />
          )}
          {isPDF && (
            <iframe
              src={attachment.view_url || attachment.download_url}
              className="w-full h-full bg-white rounded-lg"
              title={attachment.file_name}
            />
          )}
          {!isImage && !isPDF && (
            <div className="text-center text-white">
              <p className="text-lg mb-4">Preview not available for this file type</p>
              <a
                href={attachment.download_url}
                download={attachment.file_name}
                className="inline-flex items-center gap-2 px-4 py-2 bg-primary text-white rounded-md hover:bg-primary/90 transition-colors"
              >
                Download to view
              </a>
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div className="mt-4 text-center text-sm text-gray-400">
          Click outside or press ESC to close
        </div>
      </div>
    </div>
  )

  return createPortal(modalContent, document.body)
}
